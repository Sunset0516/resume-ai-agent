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
    LLM_RETRY: int = 2
    LLM_TEMPERATURE: float = 0.7
    SSE_HEARTBEAT_INTERVAL: int = 15

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
