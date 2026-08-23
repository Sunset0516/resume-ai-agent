"""
简历 AI Agent 核心服务
串联：ResumeCRUD -> MemoryService -> LLMService

提供两大能力：
1. chat()  - 单轮非流式对话
2. chat_stream() - 流式对话
"""
import json
import logging
from typing import AsyncGenerator, Tuple, Optional

from sqlalchemy.orm import Session

from .llm_service import llm_service
from .memory_service import MemoryService
from .resume_crud import ResumeCRUD
from ..models import Resume

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# System Prompt：定义 Agent 人设和行为
# ------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """你是「{name}」的私人简历 AI 助手。面试官或访客会向你提问关于求职者（{name}）的简历、背景、技能、项目经验等问题，你的任务是基于下方【简历数据】和【历史记忆】客观、准确、专业地回答。

## 角色与行为准则
1. 你代表 {name}本人，但只陈述简历中已有或可合理推断的事实，不编造信息。
2. 回答要条理清晰、重点突出、数据说话；对于项目/实习经历尽量展示成果与贡献。
3. 当问题涉及简历没有的信息，要礼貌说明"简历中未提及该信息"，并可以引导面试官查看相关部分或给出合理的替代回答。
4. 语言使用中文，专业、礼貌、自信，但不浮夸。
5. 如果访客问与求职无关的私人问题，可礼貌拒答或引导回到简历相关话题。
6. 如果访客要求总结或推荐，你可以基于简历给出简洁有力的总结。

## 简历数据（请基于此内容回答）
```
{resume_text}
```

## 长期记忆（访客偏好/高频问答）
```
{memory_text}
```
"""


class ResumeAgentService:
    """简历 AI Agent 服务"""

    def __init__(self, db: Session):
        self.db = db
        self.memory = MemoryService(db)
        self.crud = ResumeCRUD(db)

    # ------------------------------------------------------------------
    # 辅助：准备上下文
    # ------------------------------------------------------------------
    def _prepare_context(self, user_msg: str, resume: Optional[Resume] = None):
        """
        准备 LLM 上下文：
        1. 取默认简历或指定简历 -> 序列化为文本
        2. 根据用户问题检索长期记忆块
        """
        if resume is None:
            resume = self.crud.get_default()
        resume_text = self.crud.dump_resume_text(resume) if resume else "（暂无简历数据，请先在后台录入简历）"

        # 搜索长期记忆
        chunks = self.memory.search_chunks(user_msg, top_k=6)
        memory_lines = []
        for i, ch in enumerate(chunks, 1):
            label = f"[{ch.category}]" if ch.category else ""
            memory_lines.append(f"{i}. {label} {ch.content}")
        memory_text = "\n".join(memory_lines) if memory_lines else "（无相关长期记忆）"

        name = resume.name if resume else "求职者"
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            name=name,
            resume_text=resume_text,
            memory_text=memory_text,
        )
        return system_prompt, resume, chunks

    # ------------------------------------------------------------------
    # 主流程：非流式
    # ------------------------------------------------------------------
    def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        visitor_id: Optional[str] = None,
        resume: Optional[Resume] = None,
    ) -> dict:
        """
        进行一轮对话（非流式）
        返回: {reply, session_id, conversation_id, tokens_used, citations}
        """
        # 1. 获取/创建会话
        conv = self.memory.get_or_create_conversation(session_id, visitor_id=visitor_id)

        # 2. 准备上下文 + 历史消息
        system_prompt, resume_obj, chunks = self._prepare_context(message, resume)
        history = self.memory.build_history_context(conv.session_id, limit=10)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 3. 调用 LLM
        try:
            reply, tokens = llm_service.chat_completion(messages)
        except RuntimeError as e:
            logger.error(f"[Agent] LLM调用失败: {e}")
            reply = f"抱歉，AI服务暂时不可用：{e}"
            tokens = 0

        # 4. 写入记忆
        meta_citations = [{"id": c.id, "key": c.key, "category": c.category} for c in chunks]
        self.memory.add_message(conv.id, "user", message)
        self.memory.add_message(
            conv.id, "assistant", reply,
            tokens_used=tokens,
            meta={"citations": meta_citations, "resume_id": resume_obj.id if resume_obj else None},
        )

        return {
            "reply": reply,
            "session_id": conv.session_id,
            "conversation_id": conv.id,
            "tokens_used": tokens,
            "citations": [c.key or c.category for c in chunks if c.key or c.category],
        }

    # ------------------------------------------------------------------
    # 主流程：流式
    # ------------------------------------------------------------------
    async def chat_stream(
        self,
        message: str,
        session_id: Optional[str] = None,
        visitor_id: Optional[str] = None,
        resume: Optional[Resume] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话（SSE）
        以 "data: {...}\n\n" 格式输出事件
        事件类型:
          - start:  会话信息
          - chunk:  增量文本
          - end:    结束，携带最终统计
          - error:  错误
        """
        conv = self.memory.get_or_create_conversation(session_id, visitor_id=visitor_id)

        # 先写入用户消息
        self.memory.add_message(conv.id, "user", message)

        system_prompt, resume_obj, chunks = self._prepare_context(message, resume)
        history = self.memory.build_history_context(conv.session_id, limit=10)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        citations = [c.key or c.category for c in chunks if c.key or c.category]

        def _sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield _sse({
            "type": "start",
            "session_id": conv.session_id,
            "conversation_id": conv.id,
            "citations": citations,
        })

        full_reply = ""
        total_tokens = 0

        try:
            async for delta, tokens in llm_service.chat_completion_stream(messages):
                full_reply += delta
                total_tokens = tokens
                yield _sse({"type": "chunk", "content": delta})
        except RuntimeError as e:
            err = str(e)
            logger.error(f"[Agent] 流式调用失败: {err}")
            yield _sse({"type": "error", "message": err})
            full_reply = f"抱歉，AI服务出现问题：{err}"

        # 最终写回助手消息
        meta_citations = [{"id": c.id, "key": c.key, "category": c.category} for c in chunks]
        self.memory.add_message(
            conv.id, "assistant", full_reply,
            tokens_used=total_tokens,
            meta={"citations": meta_citations, "resume_id": resume_obj.id if resume_obj else None},
        )

        yield _sse({
            "type": "end",
            "tokens_used": total_tokens,
            "reply_length": len(full_reply),
        })
