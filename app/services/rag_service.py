"""
简历检索服务（RAG）

职责：
1. 把结构化简历拆成「章节 + 条目」粒度的片段（教育/实习/项目/技能各成片段）
2. 调用 Embedding API 生成向量，并缓存在 resume_chunks 表（简历更新后自动重建）
3. 查询时做余弦相似度检索，返回片段与章节引用；向量不可用时降级为关键词检索

设计取舍：
- 概览类问题（总结/介绍/评价）直接注入完整简历，避免只取到片段导致回答不完整
- 具体问题走检索，只把相关的几条片段喂给 LLM，降低 token 成本并支持引用溯源
"""
import logging
import math
from typing import List, Optional, Tuple, Dict

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Resume, ResumeChunk
from .memory_service import tokenize

logger = logging.getLogger(__name__)

# 概览/枚举类问题：需要看完整简历，不适合只取 top-k
_BROAD_KEYWORDS = (
    "总结", "概括", "整体", "综合评价", "评价一下", "优势", "亮点",
    "匹配", "适合", "介绍一下他", "介绍下他", "说说他", "讲讲他",
    "完整简历", "哪些项目", "什么项目", "项目经历",
)


def is_broad_question(question: str) -> bool:
    q = (question or "").strip()
    return any(k in q for k in _BROAD_KEYWORDS)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingClient:
    """OpenAI 兼容格式的 Embedding 客户端（默认智谱 embedding-3）"""

    def __init__(self):
        self.api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
        self.base_url = settings.EMBEDDING_BASE_URL.rstrip("/")
        self.model = settings.EMBEDDING_MODEL
        self.timeout = 20

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def embed(self, texts: List[str], batch_size: int = 8) -> List[List[float]]:
        """批量生成向量；任一批失败则返回空列表，由调用方降级"""
        if not self.enabled or not texts:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        vectors: List[List[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i:i + batch_size]
                    resp = client.post(
                        f"{self.base_url}/embeddings",
                        headers=headers,
                        json={"model": self.model, "input": batch},
                    )
                    resp.raise_for_status()
                    data = sorted(resp.json().get("data", []), key=lambda d: d.get("index", 0))
                    if len(data) != len(batch):
                        raise RuntimeError(f"向量数量不匹配：期望 {len(batch)}，实际 {len(data)}")
                    vectors.extend([d["embedding"] for d in data])
        except Exception as e:
            logger.warning(f"[RAG] Embedding 调用失败，降级为关键词检索: {e}")
            return []
        return vectors


embedding_client = EmbeddingClient()


class ResumeRAGService:
    """简历分块检索（按 resume 维度缓存向量）"""

    def __init__(self, db: Session, owner_key: Optional[str] = None):
        self.db = db
        self.owner_key = owner_key

    # ------------------------------------------------------------------
    # 分块
    # ------------------------------------------------------------------
    def build_chunks(self, resume: Resume) -> List[dict]:
        """把简历拆成可独立检索的片段"""
        chunks: List[dict] = []

        basic = [f"姓名: {resume.name}"]
        if resume.title:
            basic.append(f"求职意向: {resume.title}")
        contacts = []
        if resume.email:
            contacts.append(f"邮箱: {resume.email}")
        if resume.phone:
            contacts.append(f"电话: {resume.phone}")
        if resume.location:
            contacts.append(f"所在地: {resume.location}")
        if resume.github:
            contacts.append(f"GitHub: {resume.github}")
        if resume.blog:
            contacts.append(f"博客: {resume.blog}")
        if contacts:
            basic.append("联系方式: " + " | ".join(contacts))
        chunks.append({
            "key": "basic", "section": "基本信息", "title": resume.name,
            "content": "\n".join(basic),
        })

        if resume.summary:
            chunks.append({
                "key": "summary", "section": "个人简介", "title": "自我评价",
                "content": resume.summary,
            })

        for e in resume.educations or []:
            parts = [f"{e.school}" + (f" · {e.degree}" if e.degree else "") +
                     (f" · {e.major}" if e.major else "")]
            if e.start_date or e.end_date:
                parts.append(f"时间: {e.start_date or '?'} - {e.end_date or '至今'}")
            if e.description:
                parts.append(f"描述: {e.description}")
            chunks.append({
                "key": f"edu:{e.id}", "section": "教育经历", "title": e.school,
                "content": "\n".join(parts),
            })

        for it in resume.internships or []:
            head = f"{it.company} · {it.position or '实习生'}"
            if it.start_date or it.end_date:
                head += f" ({it.start_date or '?'}-{it.end_date or '至今'})"
            parts = [head]
            if it.location:
                parts.append(f"地点: {it.location}")
            for h in it.highlights or []:
                parts.append(f"- {h}")
            chunks.append({
                "key": f"int:{it.id}", "section": "实习经历", "title": it.company,
                "content": "\n".join(parts),
            })

        for p in resume.projects or []:
            head = f"{p.name} · {p.role or '参与'}"
            if p.start_date or p.end_date:
                head += f" ({p.start_date or '?'}-{p.end_date or '至今'})"
            parts = [head]
            if p.tech_stack:
                parts.append(f"技术栈: {', '.join(p.tech_stack)}")
            if p.description:
                parts.append(f"描述: {p.description}")
            for h in p.highlights or []:
                parts.append(f"- {h}")
            chunks.append({
                "key": f"proj:{p.id}", "section": "项目经验", "title": p.name,
                "content": "\n".join(parts),
            })

        for s in resume.skills or []:
            items = ", ".join(s.items) if s.items else ""
            chunks.append({
                "key": f"skill:{s.id}", "section": "技能", "title": s.category or "技能",
                "content": f"{s.category or '技能'}: {items}",
            })

        return chunks

    # ------------------------------------------------------------------
    # 向量缓存
    # ------------------------------------------------------------------
    def _ensure_chunks(self, resume: Resume) -> List[ResumeChunk]:
        desired = self.build_chunks(resume)
        rows = self.db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume.id).all()
        version = resume.updated_at

        stale = len(rows) != len(desired)
        if not stale:
            for r in rows:
                if not r.resume_version or not version:
                    stale = True
                    break
                if abs((r.resume_version - version).total_seconds()) > 1:
                    stale = True
                    break

        if not stale:
            return rows

        logger.info(f"[RAG] 简历 #{resume.id} 片段重建：{len(desired)} 条")
        self.db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume.id).delete()
        vectors = embedding_client.embed([c["content"] for c in desired])
        rows = []
        for i, c in enumerate(desired):
            row = ResumeChunk(
                resume_id=resume.id,
                owner_key=self.owner_key,
                chunk_key=c["key"],
                section=c["section"],
                title=c["title"],
                content=c["content"],
                embedding=vectors[i] if i < len(vectors) else None,
                resume_version=version,
            )
            self.db.add(row)
            rows.append(row)
        self.db.commit()
        for r in rows:
            self.db.refresh(r)
        return rows

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search(self, query: str, resume: Resume,
               top_k: Optional[int] = None,
               min_score: Optional[float] = None) -> Tuple[List[Tuple[float, ResumeChunk]], str]:
        """
        返回：( [(相似度, 片段)], 检索模式 vector/keyword )
        """
        top_k = top_k or settings.RAG_TOP_K
        min_score = settings.RAG_MIN_SCORE if min_score is None else min_score

        chunks = self._ensure_chunks(resume)
        if not chunks:
            return [], "empty"

        has_vectors = all(c.embedding for c in chunks)
        if has_vectors and embedding_client.enabled:
            qvec = embedding_client.embed([query])
            if qvec:
                tokens = tokenize(query)
                scored = []
                for c in chunks:
                    score = _cosine(qvec[0], c.embedding)
                    # 混合加权：查询词命中章节/标题时给小额加分（上限 0.06），
                    # 避免纯向量把"项目"类问题排到个人简介上
                    head = f"{c.section} {c.title or ''}".lower()
                    bonus = 0.03 * sum(1 for t in tokens if t in head)
                    scored.append((score + min(bonus, 0.06), c))
                hits = [(s, c) for s, c in scored if s >= min_score]
                hits.sort(key=lambda x: x[0], reverse=True)
                return hits[:top_k], "hybrid"

        return self._keyword_search(query, chunks, top_k), "keyword"

    def _keyword_search(self, query: str, chunks: List[ResumeChunk],
                        top_k: int) -> List[Tuple[float, ResumeChunk]]:
        """向量不可用时的兜底：jieba 分词命中率排序"""
        tokens = tokenize(query)
        if not tokens:
            return []
        scored = []
        for c in chunks:
            haystack = f"{c.section} {c.title or ''} {c.content}".lower()
            hit = sum(1 for t in tokens if t in haystack)
            if hit:
                scored.append((hit / len(tokens), c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------
    @staticmethod
    def format_context(hits: List[Tuple[float, ResumeChunk]]) -> str:
        """把命中片段拼成 prompt 片段"""
        blocks = []
        for _, c in hits:
            head = f"【{c.section}】" + (f" {c.title}" if c.title else "")
            blocks.append(f"{head}\n{c.content}")
        return "\n\n".join(blocks)

    @staticmethod
    def to_citations(hits: List[Tuple[float, ResumeChunk]]) -> List[dict]:
        return [
            {
                "source": "resume",
                "section": c.section,
                "title": c.title,
                "score": round(float(score), 3),
            }
            for score, c in hits
        ]
