"""
持久记忆服务
负责：
1. 会话级记忆（Conversation + Message 增删查）
2. 长期记忆块（MemoryChunk：可跨会话复用的知识片段）
3. 记忆搜索（基于关键词 + 分类过滤 + 重要性排序）
"""
import re
import uuid
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Conversation, Message, MemoryChunk

logger = logging.getLogger(__name__)

try:
    import jieba
    jieba.setLogLevel(logging.WARNING)
except ImportError:  # 未安装 jieba 时降级为英文单词 + 单字切分
    jieba = None

# 高频、无检索意义的口语词
_STOPWORDS = {
    "的", "了", "吗", "呢", "吧", "啊", "呀", "是", "在", "有", "和", "与", "或",
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "这个", "那个", "这些",
    "那些", "什么", "怎么", "怎样", "如何", "哪些", "多少", "请问", "一下", "可以",
    "能否", "是否", "一个", "一些", "以及", "还有", "就是", "然后", "但是", "因为",
}
_WORD_RE = re.compile(r"[a-zA-Z0-9_+#\.\-]+")


def tokenize(text: str) -> List[str]:
    """中英文混合分词：jieba 切中文，正则切英文/数字，过滤停用词与单字"""
    text = (text or "").lower()
    if not text:
        return []
    if jieba is not None:
        raw = jieba.lcut(text)
    else:
        raw = _WORD_RE.findall(text) + re.findall(r"[\u4e00-\u9fff]", text)
    tokens, seen = [], set()
    for t in raw:
        t = t.strip()
        if len(t) < 2 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        tokens.append(t)
    return tokens


class MemoryService:
    """持久化记忆管理（按 owner_key 隔离）"""

    def __init__(self, db: Session, owner_key: str | None = None):
        self.db = db
        self.owner_key = owner_key

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
            owner_key=self.owner_key,
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
        if self.owner_key:
            q = q.filter((Conversation.owner_key == self.owner_key) | (Conversation.owner_key.is_(None)))
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

    def build_history_context(self, session_id: str, limit: int = 0) -> List[dict]:
        """
        构建 LLM 可用的历史消息列表（仅 user / assistant）
        已被摘要覆盖的消息不再重复注入，避免上下文膨胀
        """
        conv = self.get_conversation(session_id)
        if not conv:
            return []
        limit = limit or settings.HISTORY_LIMIT
        msgs = (
            self.db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .filter(Message.id > (conv.summary_upto_id or 0))
            .order_by(Message.id.desc())
            .limit(limit)
            .all()
        )
        history = []
        for m in reversed(msgs):
            if m.role in ("user", "assistant"):
                history.append({"role": m.role, "content": m.content})
        return history

    # ==========================================================
    # 记忆压缩：把早期消息滚动压缩成摘要
    # ==========================================================
    def get_summary(self, session_id: str) -> str:
        conv = self.get_conversation(session_id)
        return (conv.summary or "") if conv else ""

    def maybe_compress(self, conv: Conversation) -> Optional[str]:
        """
        未摘要消息超过 trigger 条时，把最早的部分压缩成摘要，
        只保留最近 keep_recent 条原文。失败时保持原状，不影响主流程。
        """
        trigger = settings.HISTORY_SUMMARY_TRIGGER
        keep = settings.HISTORY_KEEP_RECENT
        if trigger <= keep:
            return conv.summary

        rows = (
            self.db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .filter(Message.id > (conv.summary_upto_id or 0))
            .order_by(Message.id.asc())
            .all()
        )
        if len(rows) <= trigger:
            return conv.summary

        old_messages = rows[:-keep]
        transcript = "\n".join(
            f"{'访客' if m.role == 'user' else '助手'}: {m.content[:500]}"
            for m in old_messages
        )[:4000]
        prev_summary = conv.summary or "（无）"

        prompt = (
            "请把下面的多轮对话压缩成不超过 200 字的中文摘要，用于后续对话的长期记忆。\n"
            "要求：保留访客的关注点、已确认过的事实、尚未解决的问题；去掉寒暄和重复内容；"
            "不要编造对话中没有的信息。\n\n"
            f"【已有摘要】\n{prev_summary}\n\n"
            f"【新增对话】\n{transcript}\n\n"
            "只输出摘要正文，不要加标题或解释。"
        )
        try:
            from .llm_service import llm_service
            summary, _ = llm_service.chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=400,
            )
        except Exception as e:
            logger.warning(f"[Memory] 对话摘要生成失败，跳过本轮压缩: {e}")
            return conv.summary

        summary = (summary or "").strip()
        if not summary:
            return conv.summary

        conv.summary = summary
        conv.summary_upto_id = old_messages[-1].id
        self.db.commit()
        logger.info(
            f"[Memory] 会话 {conv.session_id} 压缩完成："
            f"摘要 {len(summary)} 字，覆盖至消息 #{conv.summary_upto_id}"
        )
        return summary

    # ==========================================================
    # 长期记忆块管理
    # ==========================================================
    def add_chunk(self, category: str, content: str, key: Optional[str] = None,
                  source: Optional[str] = None, importance: int = 5) -> MemoryChunk:
        """添加一条长期记忆片段"""
        chunk = MemoryChunk(
            owner_key=self.owner_key,
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
        关键词检索长期记忆（SQLite 场景，不依赖向量库）
        打分规则：
        - 只保留至少命中 1 个查询词的片段；无命中返回空，避免把无关记忆塞进 prompt
        - 排序依次比较：命中词数量 > 命中词总长度 > importance（importance 仅作平手裁决）
        """
        q = self.db.query(MemoryChunk)
        if self.owner_key:
            q = q.filter((MemoryChunk.owner_key == self.owner_key) | (MemoryChunk.owner_key.is_(None)))
        if categories:
            q = q.filter(MemoryChunk.category.in_(categories))
        candidates = q.all()

        tokens = tokenize(query)
        if not tokens or not candidates:
            logger.debug(f"[Memory] query='{query}' 无有效分词，跳过检索")
            return []

        ranked: List[Tuple[int, int, int, MemoryChunk]] = []
        for ch in candidates:
            haystack = f"{ch.key or ''} {ch.content}".lower()
            hits = [t for t in tokens if t in haystack]
            if not hits:
                continue
            ranked.append((len(hits), sum(len(t) for t in hits), ch.importance or 0, ch))

        ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        result = [item[3] for item in ranked[:top_k]]
        logger.debug(f"[Memory] query='{query}' tokens={tokens} 命中={len(ranked)} 返回={len(result)}")

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
        if self.owner_key:
            q = q.filter((MemoryChunk.owner_key == self.owner_key) | (MemoryChunk.owner_key.is_(None)))
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
