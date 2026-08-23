"""
LLM API 调用服务
支持：OpenAI / 阿里云 DashScope / 其他兼容 OpenAI 接口格式的服务
"""
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple

import requests
import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务封装"""

    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.model = settings.LLM_MODEL
        self.timeout = settings.LLM_TIMEOUT
        self.temperature = settings.LLM_TEMPERATURE
        self.provider = settings.LLM_PROVIDER.lower()

    # ------------------------------------------------------------------
    # 基础工具：格式化请求头 / URL
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        # DashScope 需要额外 header
        if self.provider == "dashscope":
            headers["X-DashScope-SSE"] = "enable"
        return headers

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    # ------------------------------------------------------------------
    # 核心：ChatCompletion 同步请求
    # ------------------------------------------------------------------
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        extra_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int]:
        """
        发起 ChatCompletion 请求（同步）
        返回：(assistant文本, 使用的token数)
        """
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra_body:
            payload.update(extra_body)

        logger.info(f"[{request_id}] LLM请求 | model={self.model} | messages_len={len(messages)}")
        start = time.time()

        try:
            resp = requests.post(
                self._chat_url(),
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.ConnectionError as e:
            logger.error(f"[{request_id}] 网络连接失败: {e}")
            raise RuntimeError(f"LLM服务连接失败，请检查网络或API地址配置: {e}")
        except requests.Timeout:
            logger.error(f"[{request_id}] 请求超时（>{self.timeout}s）")
            raise RuntimeError("LLM服务响应超时，请稍后重试")
        except requests.HTTPError as e:
            logger.error(f"[{request_id}] HTTP错误 {resp.status_code}: {resp.text[:500]}")
            raise RuntimeError(f"LLM服务返回错误: {resp.status_code} {resp.text[:300]}")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[{request_id}] 响应解析失败: {e} | 原始内容: {resp.text[:500]}")
            raise RuntimeError("LLM服务返回格式异常，无法解析")

        # 解析返回
        try:
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content", "")
            usage = data.get("usage", {})
            tokens = usage.get("total_tokens", 0)
        except (KeyError, IndexError) as e:
            logger.error(f"[{request_id}] 返回字段缺失: {e} | data={str(data)[:500]}")
            raise RuntimeError("LLM响应缺少必要字段")

        cost_ms = int((time.time() - start) * 1000)
        logger.info(f"[{request_id}] LLM响应 OK | tokens={tokens} | latency={cost_ms}ms | "
                    f"preview={content[:50].replace(chr(10), ' ')}")
        return content, tokens

    # ------------------------------------------------------------------
    # 流式响应
    # ------------------------------------------------------------------
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Tuple[str, int], None]:
        """
        流式 ChatCompletion（基于 httpx AsyncClient + SSE）
        生成: (增量文本, 累计token数)
        """
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": True,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        logger.info(f"[{request_id}] LLM流式请求 | model={self.model}")

        total_tokens = 0
        full_content = ""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    self._chat_url(),
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_chunk = line[len("data:"):].strip()
                        if data_chunk == "[DONE]":
                            break
                        try:
                            obj = json.loads(data_chunk)
                        except json.JSONDecodeError:
                            continue
                        # 抽取 delta
                        try:
                            delta = obj["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            usage = obj.get("usage")
                            if usage:
                                total_tokens = usage.get("total_tokens", total_tokens)
                        except (KeyError, IndexError):
                            continue
                        if content:
                            full_content += content
                            yield content, total_tokens
            except httpx.ConnectError as e:
                logger.error(f"[{request_id}] 流式连接失败: {e}")
                raise RuntimeError(f"LLM服务连接失败: {e}")
            except httpx.TimeoutException:
                logger.error(f"[{request_id}] 流式请求超时")
                raise RuntimeError("LLM流式响应超时")
            except httpx.HTTPStatusError as e:
                logger.error(f"[{request_id}] 流式HTTP错误: {e.response.status_code}")
                raise RuntimeError(f"LLM服务错误: {e.response.status_code}")

        logger.info(f"[{request_id}] 流式结束 | 累计长度={len(full_content)} | tokens={total_tokens}")

    # ------------------------------------------------------------------
    # 辅助：构造 Prompt 的便捷方法
    # ------------------------------------------------------------------
    def build_messages(self, system_prompt: str, user_prompt: str,
                       history: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        """组装标准 messages 数组"""
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})
        return messages


# 全局单例
llm_service = LLMService()
