"""语义缓存服务：相似问题直接命中缓存回答，省一次 LLM 调用（性能优化）。

原理：把每个问题的向量 + 回答缓存起来，新问题先求向量，
与缓存中所有问题向量做余弦相似度，超过阈值即视为"同义问题"，直接返回缓存答案。
- 语义缓存比精确缓存更强的关键：换一种说法也能命中（如 "退货运费谁出" ≈ "退货要运费吗"）
- 存储可插拔：配置 REDIS_URL 用 Redis（生产多实例共享），否则内存实现（开发/单机）
"""
import json
import math
import threading
from typing import Any

from ..config import settings

# 单例
_cache: "SemanticCache | None" = None
_lock = threading.Lock()


def _cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度：两向量夹角的余弦值，取值 [-1, 1]，越大越相似。"""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class SemanticCache:
    """基于向量相似度的问答缓存。"""

    def __init__(self) -> None:
        self.max_size = settings.CACHE_MAX_ENTRIES
        self.threshold = settings.CACHE_SIMILARITY_THRESHOLD
        self._memory: list[dict[str, Any]] = []  # 内存实现（无 Redis 时）
        self._redis = None
        if settings.REDIS_URL:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self._key = "rag:semantic_cache"

    async def _load(self) -> list[dict]:
        if self._redis:
            raw = await self._redis.get(self._key)
            return json.loads(raw) if raw else []
        return self._memory

    async def _save(self, entries: list[dict]) -> None:
        if self._redis:
            # 存 JSON 列表，TTL 一天；命中后由 set() 续写
            await self._redis.set(self._key, json.dumps(entries, ensure_ascii=False), ex=86400)
        else:
            self._memory = entries

    async def get(self, query_embedding: list[float]) -> tuple[str, list] | None:
        """返回 (回答, 引用列表)；未命中返回 None。"""
        entries = await self._load()
        if not entries:
            return None
        best_sim, best_entry = -1.0, None
        for e in entries:
            sim = _cosine(query_embedding, e["embedding"])
            if sim > best_sim:
                best_sim, best_entry = sim, e
        if best_entry is not None and best_sim >= self.threshold:
            return best_entry["answer"], best_entry["citations"]
        return None

    async def set(
        self,
        query_embedding: list[float],
        question: str,
        answer: str,
        citations: list,
    ) -> None:
        entries = await _load_safe(self)
        entries.append(
            {
                "embedding": query_embedding,
                "question": question,
                "answer": answer,
                "citations": citations,
            }
        )
        # 只保留最近 N 条（LRU 近似：淘汰最旧）
        entries = entries[-self.max_size:]
        await self._save(entries)

    async def clear(self) -> int:
        entries = await self._load()
        n = len(entries)
        await self._save([])
        return n


async def _load_safe(cache: SemanticCache) -> list[dict]:
    """set() 时避免 Redis 读取失败导致写入崩溃。"""
    try:
        return await cache._load()
    except Exception:
        return []


def get_cache() -> SemanticCache:
    """获取全局语义缓存单例。"""
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = SemanticCache()
    return _cache
