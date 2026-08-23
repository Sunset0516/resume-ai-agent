"""
长期记忆块管理 API
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..main import get_owner_key
from ..schemas import MemoryChunkCreate, MemoryChunk as MemoryChunkSchema, ApiResponse
from ..services.memory_service import MemoryService

router = APIRouter(prefix="/api/memory", tags=["长期记忆"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ApiResponse[MemoryChunkSchema])
def create_chunk(data: MemoryChunkCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    """手动添加一条长期记忆"""
    mem = MemoryService(db, owner_key=owner_key)
    chunk = mem.add_chunk(
        category=data.category,
        content=data.content,
        key=data.key,
        source=data.source,
        importance=data.importance,
    )
    return ApiResponse(data=chunk, message="记忆已添加")


@router.get("", response_model=ApiResponse[List[MemoryChunkSchema]])
def list_chunks(
    category: Optional[str] = Query(None, description="分类过滤"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """列出记忆"""
    mem = MemoryService(db, owner_key=owner_key)
    return ApiResponse(data=mem.list_chunks(category=category, limit=limit))


@router.get("/search", response_model=ApiResponse[List[MemoryChunkSchema]])
def search_memory(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    category: Optional[str] = Query(None),
    top_k: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """搜索记忆"""
    mem = MemoryService(db, owner_key=owner_key)
    cats = [category] if category else None
    chunks = mem.search_chunks(q, categories=cats, top_k=top_k)
    return ApiResponse(data=chunks)


@router.delete("/{chunk_id}", response_model=ApiResponse)
def delete_chunk(chunk_id: int, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    mem = MemoryService(db, owner_key=owner_key)
    if not mem.delete_chunk(chunk_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return ApiResponse(message="记忆已删除")
