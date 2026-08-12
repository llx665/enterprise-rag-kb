"""检索测试：稠密/稀疏两路命中均携带 parent_content，RRF 融合不丢字段。"""
import pytest

from app.services import retriever


class _FakePoint:
    """Qdrant 命中点桩：payload + score。"""

    def __init__(self, payload: dict, score: float):
        self.payload = payload
        self.score = score


class _FakeSearch:
    """vector_store.search 桩：返回固定命中。"""

    def __init__(self, hits):
        self._hits = hits

    async def __call__(self, vector, limit):
        return self._hits


async def test_dense_retrieve_carries_parent_content(monkeypatch):
    """稠密检索命中带 parent_content（payload 有则透传，无则空串）。"""

    async def _fake_search(vector, limit):
        return [
            _FakePoint(
                {
                    "doc_id": 1,
                    "filename": "手机数码.md",
                    "chunk_index": 2,
                    "content": "子块内容",
                    "parent_content": "父块全文",
                },
                0.91,
            ),
            # 旧数据无 parent_content → 应回退为空串（不抛 KeyError）
            _FakePoint({"doc_id": 2, "filename": "a.md", "chunk_index": 0, "content": "旧块"}, 0.5),
        ]

    monkeypatch.setattr(retriever.vector_store, "search", _fake_search)
    hits = await retriever._dense_retrieve("问题", limit=10, vector=[0.1] * 3)
    assert hits[0]["parent_content"] == "父块全文"
    assert hits[1]["parent_content"] == ""
    assert hits[0]["content"] == "子块内容"


def test_bm25_search_carries_parent_content(monkeypatch):
    """稀疏检索命中带 parent_content（语料行含第 6 项）。"""
    rows = [
        (1, 1, "接口示例.py", 0, "创建订单的函数", "class OrderService:\n    def create_order"),
        (2, 1, "接口示例.py", 1, "支付订单的函数", "class OrderService:\n    def pay_order"),
        (3, 2, "商品知识库.md", 0, "查询商品库存信息", "库存查询流程"),
        (4, 3, "会员中心.md", 0, "会员积分累计规则说明", "积分规则"),
        (5, 4, "物流配送.md", 0, "物流配送时效与运费计算", "物流规则"),
        (6, 5, "售后政策.md", 0, "售后退换货政策条款", "售后条款"),
        (7, 6, "发票指南.md", 0, "发票开具流程指引", "开票流程"),
        (8, 7, "优惠券.md", 0, "优惠券领取和使用方法", "券规则"),
    ]
    hits = retriever._bm25_search(rows, "创建订单", limit=10)
    assert hits, "应命中创建订单相关块"
    assert all("parent_content" in h for h in hits)
    create_order_hit = next(h for h in hits if "创建订单" in h["content"])
    assert "class OrderService" in create_order_hit["parent_content"]


def test_rrf_fuse_preserves_parent_content():
    """RRF 融合保留 parent_content（两路命中都带该字段）。"""
    dense = [
        {
            "doc_id": 1,
            "doc_name": "a.md",
            "chunk_index": 0,
            "content": "c0",
            "parent_content": "p0",
            "score": 0.9,
        }
    ]
    sparse = [
        {
            "doc_id": 1,
            "doc_name": "a.md",
            "chunk_index": 0,
            "content": "c0",
            "parent_content": "p0",
            "score": 0.5,
        }
    ]
    fused = retriever._rrf_fuse(dense, sparse, top_k=5)
    assert len(fused) == 1
    assert fused[0]["parent_content"] == "p0"
