"""
数据库连接与会话管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from .config import settings

# SQLite 引擎配置（支持多线程访问）
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    poolclass=StaticPool if settings.DATABASE_URL.startswith("sqlite") else None,
    echo=settings.DEBUG,
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 模型基类
Base = declarative_base()


def get_db():
    """FastAPI依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表结构"""
    # 导入模型确保Base.metadata包含所有表
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_sqlite_migrations()


def _run_sqlite_migrations():
    """SQLite 自动迁移：新增列（列已存在则跳过）"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    import logging as _lg
    from sqlalchemy import text
    lg = _lg.getLogger("db")
    migrations = [
        ("resumes", "owner_key", "ALTER TABLE resumes ADD COLUMN owner_key VARCHAR(100)"),
        ("memory_chunks", "owner_key", "ALTER TABLE memory_chunks ADD COLUMN owner_key VARCHAR(100)"),
        ("conversations", "owner_key", "ALTER TABLE conversations ADD COLUMN owner_key VARCHAR(100)"),
        ("conversations", "summary", "ALTER TABLE conversations ADD COLUMN summary TEXT"),
        ("conversations", "summary_upto_id", "ALTER TABLE conversations ADD COLUMN summary_upto_id INTEGER DEFAULT 0"),
    ]
    with engine.connect() as conn:
        for table, col, sql in migrations:
            try:
                rs = conn.execute(text(f"PRAGMA table_info({table})"))
                cols = [r[1] for r in rs.fetchall()]
                if col not in cols:
                    conn.execute(text(sql))
                    conn.commit()
                    lg.info(f"[migrate] {table}.{col} 新增成功")
                else:
                    lg.info(f"[migrate] {table}.{col} 已存在，跳过")
            except Exception as e:
                lg.warning(f"[migrate] {table}.{col} skip: {e}")
