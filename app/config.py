"""
全局配置管理
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置类"""

    # ---------- LLM API 配置 ----------
    LLM_PROVIDER: str = "openai"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: int = 120
    LLM_STREAM_TIMEOUT: int = 180
    LLM_FIRST_CHUNK_TIMEOUT: int = 30
    LLM_RETRY: int = 1          # 重试次数：与空闲超时叠加会放大总耗时，默认只重试 1 次
    LLM_TEMPERATURE: float = 0.7
    LLM_STREAM_USAGE: bool = True  # 流式请求是否要求服务端返回 usage（用于准确统计 token）
    SSE_HEARTBEAT_INTERVAL: int = 15

    # ---------- Embedding / 检索配置 ----------
    EMBEDDING_API_KEY: str = ""       # 留空则复用 LLM_API_KEY
    EMBEDDING_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_DIM: int = 1024
    RAG_ENABLED: bool = True
    RAG_TOP_K: int = 4
    RAG_MIN_SCORE: float = 0.30
    RAG_RECALL_K: int = 12            # 一阶段召回条数，作为重排候选池

    # ---------- Rerank 精排配置 ----------
    RERANK_ENABLED: bool = True
    RERANK_API_KEY: str = ""          # 留空则复用 LLM_API_KEY
    RERANK_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    RERANK_MODEL: str = "rerank"

    # ---------- 记忆压缩配置 ----------
    HISTORY_LIMIT: int = 10
    HISTORY_SUMMARY_TRIGGER: int = 12   # 未摘要消息超过该数量时触发压缩
    HISTORY_KEEP_RECENT: int = 6        # 压缩后保留的最近消息条数

    # ---------- 服务配置 ----------
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # ---------- 数据库配置 ----------
    DATABASE_URL: str = "sqlite:///./data/resume_agent.db"

    # ---------- 安全配置 ----------
    API_SECRET: Optional[str] = None

    class Config:
        env_file = str(BASE_DIR / ".env")
        case_sensitive = True
        extra = "allow"


# 全局配置实例
settings = Settings()


def ensure_directories():
    """确保必要的目录存在"""
    os.makedirs(BASE_DIR / "data", exist_ok=True)
    os.makedirs(BASE_DIR / "static", exist_ok=True)
