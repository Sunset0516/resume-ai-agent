"""
个人实习生简历 AI Agent - FastAPI 入口
启动命令:
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
或者直接:
    python run.py
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from .config import settings, BASE_DIR, ensure_directories
from .database import init_db, get_db
from .api import chat as chat_router
from .api import resume as resume_router
from .api import memory as memory_router

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("resume-agent")


# ---------- 生命周期 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    init_db()
    logger.info("=" * 50)
    logger.info("  简历 AI Agent 服务已启动")
    logger.info(f"  访问地址: http://{settings.HOST}:{settings.PORT}")
    logger.info(f"  管理后台: http://{settings.HOST}:{settings.PORT}/admin")
    logger.info(f"  API 文档: http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"  LLM 模型: {settings.LLM_MODEL} ({settings.LLM_BASE_URL})")
    logger.info(f"  数据库:   {settings.DATABASE_URL}")
    if not settings.LLM_API_KEY or settings.LLM_API_KEY.startswith("your_"):
        logger.warning("  ⚠ 未配置有效的 LLM_API_KEY，聊天功能会返回错误")
    logger.info("=" * 50)
    yield
    logger.info("服务已停止")


# ---------- FastAPI 应用 ----------
app = FastAPI(
    title="个人实习生简历 AI Agent",
    description="支持 API 调用、持久记忆、可上线部署的简历问答网站",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置（允许从任意域名访问，部署上线时建议限制到具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源
static_path = BASE_DIR / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


# ---------- API Key 验证（可选） ----------
async def verify_api_secret(request: Request):
    if not settings.API_SECRET:
        return
    key = request.headers.get("X-API-Secret") or request.query_params.get("api_secret")
    if key != settings.API_SECRET:
        raise HTTPException(status_code=401, detail="无效的 API_SECRET")


# ---------- 页面路由 ----------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index_page(request: Request):
    """前台：简历 + 聊天页面"""
    return templates.TemplateResponse(request, "index.html")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(request: Request):
    """后台：简历编辑 + 记忆管理"""
    return templates.TemplateResponse(request, "admin.html")


@app.get("/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "service": "resume-ai-agent", "version": "1.0.0"}


# ---------- 挂载 API 路由 ----------
app.include_router(chat_router.router, dependencies=[Depends(verify_api_secret)])
app.include_router(resume_router.router, dependencies=[Depends(verify_api_secret)])
app.include_router(memory_router.router, dependencies=[Depends(verify_api_secret)])


# ---------- 错误处理（统一返回 JSON） ----------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    from fastapi.responses import JSONResponse
    logger.error(f"未捕获异常: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": f"服务器内部错误: {exc}", "code": 500},
    )
