"""混合检索服务：稠密向量检索 + 稀疏关键词检索，RRF 融合（性能优化核心）。

设计动机（企业级 RAG 的召回率提升）：
- 稠密检索（Qdrant 向量）：捕获语义相似 —— 换一种说法也能命中
- 稀疏检索（jieba + BM25）：精确匹配商品名/型号/参数 —— 短关键词、专有名词不丢
- RRF（Reciprocal Rank Fusion）融合：两路检索按排名倒数和融合，鲁棒且无需调参

整条链路：query -> embedding（Qdrant 稠密检索）
                   -> jieba 分词 -> BM25 打分（稀疏检索）
                   -> RRF 融合 ->（可选 bge-reranker 精排）-> top_k
"""
import asyncio
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..config import settings
from ..database import SessionLocal
from ..models import DocumentChunk
from . import vector_store
from .embedding import get_embeddings

# BM25 语料缓存：key 为分块表的 (总数, 最大 id)，任何文档增删都会使其失效
_corpus_cache: dict = {"version": None, "rows": None}

# 重排序模型缓存（懒加载，默认关闭）
_reranker: object | None = None


# ==========================================================
# 稠密检索：query -> embedding -> Qdrant
# ==========================================================
async def _dense_retrieve(query: str, limit: int, vector: list[float] | None) -> list[dict]:
    if vector is None:
        vector = await get_embeddings().aembed_query(query)
    hits = await vector_store.search(vector, limit=limit)
    return [
        {
            "doc_id": h.payload.get("doc_id"),
            "doc_name": h.payload.get("filename", ""),
            "chunk_index": h.payload.get("chunk_index", 0),
            "content": h.payload.get("content", ""),
            "score": h.score,
        }
        for h in hits
    ]


# ==========================================================
# 稀疏检索：jieba 分词 + BM25
# ==========================================================
def _tokenize(text: str) -> list[str]:
    """中文分词：cut_for_search 会补充粒度更细的搜索词，提升召回。"""
    from jieba import cut_for_search

    return [w for w in cut_for_search(text) if w.strip()]


async def _load_corpus() -> list[tuple]:
    """全量加载分块语料（带版本缓存，文档变更自动重建）。"""
    async with SessionLocal() as db:
        total = await db.scalar(select(func.count()).select_from(DocumentChunk))
        max_id = await db.scalar(select(func.max(DocumentChunk.id)))
        version = (total, max_id)
        if _corpus_cache["version"] != version:
            rows = await db.scalars(
                select(DocumentChunk)
                .options(joinedload(DocumentChunk.document))
                .order_by(DocumentChunk.id)
            )
            _corpus_cache["rows"] = [
                (c.id, c.doc_id, c.document.filename, c.chunk_index, c.content)
                for c in rows
            ]
            _corpus_cache["version"] = version
        return _corpus_cache["rows"]


async def _sparse_retrieve(query: str, limit: int) -> list[dict]:
    # 语料加载走异步 DB；BM25 打分为纯 CPU 计算，丢线程池避免阻塞事件循环
    rows = await _load_corpus()
    if not rows:
        return []
    return await asyncio.to_thread(_bm25_search, rows, query, limit)


def _bm25_search(rows: list[tuple], query: str, limit: int) -> list[dict]:
    from rank_bm25 import BM25Okapi

    tokenized_corpus = [_tokenize(r[4]) for r in rows]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    hits = []
    for i in ranked_idx:
        if scores[i] <= 0:  # 与查询零重叠的直接截断
            break
        _id, doc_id, doc_name, chunk_index, content = rows[i]
        hits.append(
            {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "chunk_index": chunk_index,
                "content": content,
                "score": round(float(scores[i]), 4),
            }
        )
        if len(hits) >= limit:
            break
    return hits


# ==========================================================
# RRF 融合
# ==========================================================
def _rrf_fuse(dense: list[dict], sparse: list[dict], top_k: int) -> list[dict]:
    fused: dict[tuple, dict] = {}
    for rank, hit in enumerate(dense):
        key = (hit["doc_id"], hit["chunk_index"])
        if key not in fused:
            fused[key] = {**hit, "score": 0.0}
        fused[key]["score"] += 1.0 / (settings.RRF_K + rank + 1)
    for rank, hit in enumerate(sparse):
        key = (hit["doc_id"], hit["chunk_index"])
        if key not in fused:
            fused[key] = {**hit, "score": 0.0}
        fused[key]["score"] += 1.0 / (settings.RRF_K + rank + 1)

    ranked = sorted(fused.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]


# ==========================================================
# 可选重排：bge-reranker 交叉编码器精排
# ==========================================================
@lru_cache
def _load_reranker():
    """懒加载重排序模型。模型未下载则返回 None（自动降级为不重排）。"""
    from pathlib import Path

    model_path = Path(settings.RERANK_MODEL_PATH)
    if not model_path.exists():
        return None
    from sentence_transformers import CrossEncoder

    return CrossEncoder(str(model_path), device="cpu")


def _maybe_rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
    """对 RRF 融合结果再做一次精排（交叉编码器打分，比双塔检索更准）。"""
    reranker = _load_reranker()
    if reranker is None or len(hits) <= 1:
        return hits
    pairs = [(query, h["content"]) for h in hits]
    scores = reranker.predict(pairs)  # CPU 推理，直接打分
    for h, s in zip(hits, scores):
        h["score"] = round(float(s), 4)  # 重排后分数替换为交叉编码器得分
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:top_k]


# ==========================================================
# 对外统一入口
# ==========================================================
async def hybrid_retrieve(
    query: str,
    top_k: int | None = None,
    vector: list[float] | None = None,
) -> list[dict]:
    """混合检索主入口。

    Args:
        query: 用户问题
        top_k: 最终返回的候选块数
        vector: 预计算的 query 向量（避免重复 embed；语义缓存已算过时传入）
    """
    top_k = top_k or settings.RETRIEVE_TOP_K
    # 两路检索各取 top_k*2，融合后仍有足够候选给重排精挑
    dense_hits, sparse_hits = await asyncio.gather(
        _dense_retrieve(query, top_k * 2, vector),
        _sparse_retrieve(query, top_k * 2),
    )
    fused = _rrf_fuse(dense_hits, sparse_hits, top_k * 2)

    if settings.RERANK_ENABLED:
        fused = await asyncio.to_thread(_maybe_rerank, query, fused, top_k)

    return fused[:top_k]
