"""
聊天 API 路由
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ChatRequest, ChatResponse, ApiResponse
from ..services.agent_service import ResumeAgentService
from ..services.memory_service import MemoryService

router = APIRouter(prefix="/api/chat", tags=["聊天对话"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ApiResponse[ChatResponse])
async def chat_endpoint(
    req: ChatRequest,
    x_visitor_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """
    非流式聊天接口
    - message: 用户问题（必填）
    - session_id: 会话ID，不传会自动新建
    - visitor_id: 访客标识，也可通过请求头 X-Visitor-Id 传入
    """
    visitor_id = req.visitor_id or x_visitor_id
    agent = ResumeAgentService(db)
    try:
        result = agent.chat(
            message=req.message,
            session_id=req.session_id,
            visitor_id=visitor_id,
        )
    except Exception as e:
        logger.exception("聊天处理异常")
        raise HTTPException(status_code=500, detail=str(e))

    return ApiResponse(data=ChatResponse(**result))


@router.post("/stream")
async def chat_stream_endpoint(
    req: ChatRequest,
    x_visitor_id: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """
    流式聊天接口（SSE）
    返回 text/event-stream 事件流：
      data: {"type": "start", ...}
      data: {"type": "chunk", "content": "..."}
      data: {"type": "end", ...}
    """
    visitor_id = req.visitor_id or x_visitor_id
    agent = ResumeAgentService(db)

    async def event_generator():
        async for chunk in agent.chat_stream(
            message=req.message,
            session_id=req.session_id,
            visitor_id=visitor_id,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions", response_model=ApiResponse)
def list_sessions(
    visitor_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取会话列表（按最近更新排序）"""
    mem = MemoryService(db)
    convs = mem.list_conversations(visitor_id=visitor_id)
    data = []
    for c in convs:
        last_msg = c.messages[-1].content if c.messages else None
        data.append({
            "id": c.id,
            "session_id": c.session_id,
            "title": c.title,
            "last_message": (last_msg[:60] + "...") if last_msg and len(last_msg) > 60 else last_msg,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        })
    return ApiResponse(data=data)


@router.get("/session/{session_id}/messages", response_model=ApiResponse)
def get_session_messages(
    session_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """获取某个会话的历史消息"""
    mem = MemoryService(db)
    conv = mem.get_conversation(session_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    msgs = mem.get_recent_messages(session_id, limit=limit)
    data = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tokens_used": m.tokens_used,
            "meta": m.meta,
            "created_at": m.created_at,
        }
        for m in msgs
    ]
    return ApiResponse(data={
        "conversation": {
            "id": conv.id,
            "session_id": conv.session_id,
            "title": conv.title,
            "created_at": conv.created_at,
        },
        "messages": data,
    })
