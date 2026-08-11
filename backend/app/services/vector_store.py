"""向量数据库服务：封装 Qdrant。

- 集合自动创建（HNSW + Cosine 距离）
- 每个向量的 payload 携带：doc_id / filename / chunk_index / content
  （content 直接存在向量库里，检索结果无需回查数据库即可渲染引用）
- 支持按文档批量删除（用于删除/重建索引）
"""
from qdrant_client import AsyncQdrantClient, models

from ..config import settings

_client: AsyncQdrantClient | None = None
# 集合是否已确保存在（避免每次检索都探一次）
_collection_ready = False


def get_client() -> AsyncQdrantClient:
    """获取全局 Qdrant 异步客户端（单例）。"""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=settings.QDRANT_URL)
    return _client


async def ensure_collection() -> None:
    """创建集合（HNSW 向量索引）。幂等：已存在则跳过。"""
    global _collection_ready
    client = get_client()
    if not await client.collection_exists(settings.QDRANT_COLLECTION):
        await client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=models.VectorParams(
                size=settings.EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            ),
            # HNSW 索引参数：企业级检索性能关键配置
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=128),
        )
    _collection_ready = True


async def _ensure() -> None:
    """惰性确保集合存在（写入 / 检索前调用，首次创建后不再往返）。"""
    global _collection_ready
    if not _collection_ready:
        await ensure_collection()


async def upsert_points(points_data: list[dict]) -> None:
    """批量写入向量点。

    points_data: [{point_id, vector, payload}]
    """
    await _ensure()
    client = get_client()
    points = [
        models.PointStruct(
            id=p["point_id"],
            vector=p["vector"],
            payload=p["payload"],
        )
        for p in points_data
    ]
    await client.upsert(settings.QDRANT_COLLECTION, points=points)


async def search(vector: list[float], limit: int = 10) -> list:
    """按向量检索，返回 hit 列表（含 payload 与相似度分数）。

    注意：qdrant-client 1.19 起 `search` 已改名 `query_points`，
    返回 QueryResponse，命中列表在其 `.points` 字段。
    """
    await _ensure()
    client = get_client()
    result = await client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vector,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return result.points


async def delete_by_doc(doc_id: int) -> None:
    """按文档 ID 删除其全部向量点（payload 过滤）。"""
    await _ensure()
    client = get_client()
    await client.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )


async def count_points() -> int:
    client = get_client()
    try:
        result = await client.count(settings.QDRANT_COLLECTION)
        return result.count
    except Exception:
        return 0


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
