"""
持久记忆服务
负责：
1. 会话级记忆（Conversation + Message 增删查）
2. 长期记忆块（MemoryChunk：可跨会话复用的知识片段）
3. 记忆搜索（基于关键词 + 分类过滤 + 重要性排序）
"""
import uuid
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from ..models import Conversation, Message, MemoryChunk

logger = logging.getLogger(__name__)


class MemoryService:
    """持久化记忆管理"""

    def __init__(self, db: Session):
        self.db = db

    # ==========================================================
    # 会话级记忆管理
    # ==========================================================
    def get_or_create_conversation(
        self,
        session_id: Optional[str] = None,
        visitor_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Conversation:
        """获取或创建会话"""
        if session_id:
            conv = self.db.query(Conversation).filter(
                Conversation.session_id == session_id
            ).first()
            if conv:
                return conv
        # 新建会话
        session_id = session_id or f"sess_{uuid.uuid4().hex[:16]}"
        conv = Conversation(
            session_id=session_id,
            visitor_id=visitor_id,
            title=title or "新会话",
            is_active=True,
        )
        self.db.add(conv)
        self.db.commit()
        self.db.refresh(conv)
        logger.info(f"[Memory] 创建新会话 session_id={session_id}")
        return conv

    def get_conversation(self, session_id: str) -> Optional[Conversation]:
        return self.db.query(Conversation).filter(
            Conversation.session_id == session_id
        ).first()

    def list_conversations(self, visitor_id: Optional[str] = None,
                           limit: int = 50) -> List[Conversation]:
        q = self.db.query(Conversation)
        if visitor_id:
            q = q.filter(Conversation.visitor_id == visitor_id)
        return q.order_by(Conversation.updated_at.desc()).limit(limit).all()

    def add_message(self, conversation_id: int, role: str, content: str,
                    tokens_used: int = 0, meta: Optional[dict] = None) -> Message:
        """向会话追加一条消息"""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tokens_used=tokens_used,
            meta=meta or {},
        )
        self.db.add(msg)
        # 刷新会话更新时间
        conv = self.db.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.utcnow()
            # 自动设置第一条消息为标题
            if conv.title == "新会话" and role == "user":
                conv.title = content[:30] + ("..." if len(content) > 30 else "")
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_recent_messages(self, session_id: str, limit: int = 20) -> List[Message]:
        """获取会话最近N条消息（用于构建LLM上下文）"""
        conv = self.get_conversation(session_id)
        if not conv:
            return []
        msgs = self.db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).limit(limit).all()
        # 倒序返回（时间正序）
        return list(reversed(msgs))

    def build_history_context(self, session_id: str, limit: int = 10) -> List[dict]:
        """
        构建 LLM 可用的历史消息列表（仅 user / assistant）
        返回: [{"role": "user", "content": "..."}, ...]
        """
        msgs = self.get_recent_messages(session_id, limit=limit)
        history = []
        for m in msgs:
            if m.role in ("user", "assistant"):
                history.append({"role": m.role, "content": m.content})
        return history

    # ==========================================================
    # 长期记忆块管理
    # ==========================================================
    def add_chunk(self, category: str, content: str, key: Optional[str] = None,
                  source: Optional[str] = None, importance: int = 5) -> MemoryChunk:
        """添加一条长期记忆片段"""
        chunk = MemoryChunk(
            category=category,
            key=key,
            content=content,
            source=source,
            importance=max(1, min(10, importance)),
        )
        self.db.add(chunk)
        self.db.commit()
        self.db.refresh(chunk)
        logger.info(f"[Memory] 新增记忆 chunk_id={chunk.id} category={category}")
        return chunk

    def search_chunks(self, query: str, categories: Optional[List[str]] = None,
                      top_k: int = 8) -> List[MemoryChunk]:
        """
        简单关键词搜索记忆（适合SQLite场景，未来可接入向量检索）
        策略：
        - 按 query 分词做 LIKE 匹配
        - 结合重要性 + 命中次数综合排序
        """
        q = self.db.query(MemoryChunk)
        if categories:
            q = q.filter(MemoryChunk.category.in_(categories))
        candidates = q.order_by(MemoryChunk.importance.desc()).all()

        # 简单关键词打分
        tokens = [t.strip() for t in query.replace(",", " ").replace("，", " ").split() if t.strip()]
        scored: List[Tuple[int, MemoryChunk]] = []
        for ch in candidates:
            score = 0
            haystack = f"{ch.key or ''} {ch.content}"
            for tok in tokens:
                if tok and tok in haystack:
                    score += 3
            score += ch.importance
            if score > 0:
                scored.append((score, ch))

        scored.sort(key=lambda x: x[0], reverse=True)
        result = [ch for _, ch in scored[:top_k]]

        # 更新访问次数
        for ch in result:
            ch.access_count += 1
            ch.last_accessed = datetime.utcnow()
        if result:
            self.db.commit()

        logger.debug(f"[Memory] 记忆搜索 query='{query}' 返回 {len(result)} 条")
        return result

    def list_chunks(self, category: Optional[str] = None, limit: int = 100) -> List[MemoryChunk]:
        q = self.db.query(MemoryChunk)
        if category:
            q = q.filter(MemoryChunk.category == category)
        return q.order_by(MemoryChunk.importance.desc(), MemoryChunk.created_at.desc()).limit(limit).all()

    def delete_chunk(self, chunk_id: int) -> bool:
        ch = self.db.get(MemoryChunk, chunk_id)
        if not ch:
            return False
        self.db.delete(ch)
        self.db.commit()
        return True
