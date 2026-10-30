"""
简历检索评测脚本（离线跑分，不调用生成模型）

对比四种检索方式在同一评测集上的表现：
1. 关键词检索（jieba 分词 + 命中率）
2. 向量检索（Embedding + 余弦相似度）
3. 混合检索（向量 + 章节词加权）
4. 混合召回 + Rerank 精排（智谱 rerank）

指标：Recall@1 / Recall@4 / MRR，以及单题平均检索耗时。
运行：
    python eval/run_eval.py
"""
import json
import sys
import time
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING)

from app.database import SessionLocal, init_db  # noqa: E402
from app.services.resume_crud import ResumeCRUD  # noqa: E402
from app.services.rag_service import (  # noqa: E402
    ResumeRAGService, embedding_client, rerank_client, _cosine, is_broad_question,
)
from app.services.memory_service import tokenize  # noqa: E402

EVAL_FILE = Path(__file__).resolve().parent / "eval_set.json"
TOP_K = 4
RECALL_K = 12


# ---------------------- 三种检索实现 ----------------------
def keyword_rank(chunks, question, _qvec=None):
    tokens = tokenize(question)
    scored = []
    for c in chunks:
        text = f'{c["section"]} {c["title"] or ""} {c["content"]}'.lower()
        hit = sum(1 for t in tokens if t in text)
        if hit:
            scored.append((hit / len(tokens), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:TOP_K]


def vector_rank(chunks, question, qvec):
    if not qvec:
        return []
    scored = [(_cosine(qvec, v), c) for c, v in zip(chunks, _vectors_cache) if v]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:TOP_K]


def _hybrid_scored(chunks, question, qvec):
    if not qvec:
        return []
    tokens = tokenize(question)
    scored = []
    for c, v in zip(chunks, _vectors_cache):
        if not v:
            continue
        head = f'{c["section"]} {c["title"] or ""}'.lower()
        bonus = 0.03 * sum(1 for t in tokens if t in head)
        scored.append((_cosine(qvec, v) + min(bonus, 0.06), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def hybrid_rank(chunks, question, qvec):
    return _hybrid_scored(chunks, question, qvec)[:TOP_K]


def rerank_rank(chunks, question, qvec):
    """混合召回 RECALL_K 条候选 → Rerank 精排 → 取 TOP_K；返回 (结果, 耗时ms)"""
    cand = _hybrid_scored(chunks, question, qvec)[:RECALL_K]
    if not cand or not rerank_client.enabled:
        return [], 0.0
    docs = [f'{c["section"]} {c["title"] or ""}\n{c["content"]}' for _, c in cand]
    t0 = time.perf_counter()
    ranked = rerank_client.rerank(question, docs, top_n=min(TOP_K, len(docs)))
    ms = (time.perf_counter() - t0) * 1000
    if not ranked:
        return [], ms
    return [(s, cand[i][1]) for i, s in ranked], ms


_vectors_cache = []


def first_hit_rank(result, expected):
    for i, (_, c) in enumerate(result, 1):
        if c["section"] in expected:
            return i
    return None


def evaluate(method, questions, chunks, qvecs):
    r1 = r4 = mrr = 0.0
    failures = []
    for q in questions:
        result = method(chunks, q["question"], qvecs.get(q["id"]))
        if result and result[0][1]["section"] in q["expected_sections"]:
            r1 += 1
        if any(c["section"] in q["expected_sections"] for _, c in result):
            r4 += 1
        else:
            failures.append((q["question"], q["expected_sections"], [c["section"] for _, c in result]))
        rank = first_hit_rank(result, q["expected_sections"])
        mrr += (1.0 / rank) if rank else 0.0
    n = len(questions) or 1
    return r1 / n, r4 / n, mrr / n, failures


def evaluate_rerank(questions, chunks, qvecs):
    """混合召回 + Rerank 精排，返回指标与单题平均重排耗时"""
    r1 = r4 = mrr = total_ms = 0.0
    failures = []
    for q in questions:
        result, ms = rerank_rank(chunks, q["question"], qvecs.get(q["id"]))
        total_ms += ms
        if result and result[0][1]["section"] in q["expected_sections"]:
            r1 += 1
        if any(c["section"] in q["expected_sections"] for _, c in result):
            r4 += 1
        else:
            failures.append((q["question"], q["expected_sections"], [c["section"] for _, c in result]))
        rank = first_hit_rank(result, q["expected_sections"])
        mrr += (1.0 / rank) if rank else 0.0
    n = len(questions) or 1
    return r1 / n, r4 / n, mrr / n, failures, total_ms / n


def main():
    init_db()
    db = SessionLocal()
    resume = ResumeCRUD(db).get_default()
    if not resume:
        print("未找到简历数据，请先录入简历后再评测")
        return

    data = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    questions = data["questions"]
    answerable = [q for q in questions if q["expected_sections"] and not is_broad_question(q["question"])]
    broad = [q for q in questions if q["expected_sections"] and is_broad_question(q["question"])]
    no_answer = [q for q in questions if q["type"] == "no_answer"]

    chunks = ResumeRAGService(db).build_chunks(resume)
    print(f"简历：{resume.name} | 片段数：{len(chunks)} | 可回答题：{len(answerable)} | 拒答题：{len(no_answer)}")
    if broad:
        print(f"概览/枚举类问题 {len(broad)} 条走完整简历注入，不计入检索指标：{[q['question'] for q in broad]}")

    if not embedding_client.enabled:
        print("未配置 Embedding Key，仅评测关键词检索")
        r1, r4, mrr, fails = evaluate(keyword_rank, answerable, chunks, {})
        print(f"关键词检索：Recall@1={r1:.2f} Recall@4={r4:.2f} MRR={mrr:.2f}")
        return

    global _vectors_cache
    _vectors_cache = embedding_client.embed([c["content"] for c in chunks])
    if len(_vectors_cache) != len(chunks):
        print("片段向量生成失败，仅评测关键词检索")
        _vectors_cache = []

    qvecs, embed_ms = {}, 0.0
    for q in questions:
        t0 = time.perf_counter()
        vec = embedding_client.embed([q["question"]])
        embed_ms += (time.perf_counter() - t0) * 1000
        qvecs[q["id"]] = vec[0] if vec else None

    n = len(answerable)
    print("\n方法             Recall@1  Recall@4  MRR     单题耗时(含embedding)")
    print("-" * 68)
    methods = [
        ("关键词检索", keyword_rank, 0.0),
        ("向量检索", vector_rank, embed_ms / max(len(questions), 1)),
        ("混合检索", hybrid_rank, embed_ms / max(len(questions), 1)),
    ]
    all_failures = {}
    for name, fn, ms in methods:
        r1, r4, mrr, fails = evaluate(fn, answerable, chunks, qvecs)
        all_failures[name] = fails
        print(f"{name:<15}{r1:>8.2f}{r4:>10.2f}{mrr:>8.2f}{ms:>16.0f}ms")

    if rerank_client.enabled:
        r1, r4, mrr, fails, rr_ms = evaluate_rerank(answerable, chunks, qvecs)
        all_failures["混合+重排"] = fails
        total_ms = embed_ms / max(len(questions), 1) + rr_ms
        print(f"{'混合+重排':<15}{r1:>8.2f}{r4:>10.2f}{mrr:>8.2f}{total_ms:>16.0f}ms")
    else:
        print("未启用 Rerank，跳过精排对比")

    for name, fails in all_failures.items():
        if fails:
            print(f"\n{name} 未命中（{len(fails)} 条）：")
            for q, exp, got in fails:
                print(f"  - {q} | 期望 {exp} | 实际 {got}")

    # ---------- 拒答题：相似度分布，用于选择阈值 ----------
    if no_answer and _vectors_cache:
        print("\n拒答题最高相似度（用于校准 RAG_MIN_SCORE）：")
        for q in no_answer:
            qv = qvecs.get(q["id"])
            if not qv:
                continue
            top = max(_cosine(qv, v) for v in _vectors_cache if v)
            print(f"  - {q['question']} → {top:.3f}")

    valid_top1 = []
    for q in answerable:
        qv = qvecs.get(q["id"])
        if qv:
            valid_top1.append(max(_cosine(qv, v) for v in _vectors_cache if v))
    if valid_top1:
        valid_top1.sort()
        print(f"\n可回答题 top1 相似度：最低 {valid_top1[0]:.3f} / 中位 {valid_top1[len(valid_top1)//2]:.3f}")


if __name__ == "__main__":
    main()
