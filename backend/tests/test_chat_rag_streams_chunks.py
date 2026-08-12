"""chat RAG 分支 SSE 流式测试：Self-RAG 缓冲后 20 字符分块推送 + done 带 reflection。"""
import json

import pytest

from app.api import chat as chat_module
from app.services import rag_chain, self_rag

FIXED_ANSWER = "星辰X1 Pro 支持 100W 有线快充。" * 4  # 足够长，验证分块
FIXED_REFLECTION = {"enabled": True, "rounds": 2, "revised": True, "issues": ["已核对功率"]}
FAKE_HITS = [
    {
        "doc_id": 1,
        "doc_name": "手机数码.md",
        "chunk_index": 0,
        "content": "子块",
        "parent_content": "星辰X1 Pro 支持 100W 有线快充。",
        "score": 0.9,
    }
]


class _FakeEmb:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1] * 512


@pytest.fixture
def rag_mocks(monkeypatch):
    """桩化 RAG 链路的模型/检索/自省，让测试不依赖真实 LLM 与 Qdrant。"""
    monkeypatch.setattr(chat_module, "get_embeddings", lambda: _FakeEmb())

    async def _fake_retrieve(query, top_k=None, vector=None):
        return FAKE_HITS

    monkeypatch.setattr(rag_chain, "retrieve", _fake_retrieve)

    async def _fake_answer(question, history, hits, on_stage=None, summary=None):
        if on_stage is not None:
            await on_stage("criticizing")
        return FIXED_ANSWER, FIXED_REFLECTION

    monkeypatch.setattr(self_rag, "self_rag_answer", _fake_answer)


def _login(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_rag_stream_chunks_and_reflection(client, rag_mocks):
    """RAG 分支：meta(status) 在前、delta 分块≤20 字、done 携带 reflection。"""
    headers = _login(client)
    events: list[tuple[str, dict]] = []

    with client.stream(
        "POST",
        "/api/chat",
        headers=headers,
        json={"question": "星辰X1 Pro 支持多少瓦快充？"},
    ) as r:
        assert r.status_code == 200
        event = None
        for line in r.iter_lines():
            line = line.strip()
            if not line:
                event = None
                continue
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[len("data: ") :])))

    # 事件类型齐全
    types = [e for e, _ in events]
    assert "meta" in types
    assert "status" in types
    assert "delta" in types
    assert "done" in types

    # meta 带引用元数据（子块粒度）
    meta = next(d for e, d in events if e == "meta")
    assert meta["citations"][0]["doc_name"] == "手机数码.md"

    # status 事件带阶段文案
    status = next(d for e, d in events if e == "status")
    assert status["stage"] == "criticizing"

    # delta：每片 ≤ 20 字符，拼接等于最终回答
    deltas = [d["content"] for e, d in events if e == "delta"]
    assert deltas, "必须推送回答文本"
    assert all(len(c) <= 20 for c in deltas)
    assert "".join(deltas) == FIXED_ANSWER

    # done：latency 非负、cached=False、reflection 原样携带
    done = next(d for e, d in events if e == "done")
    assert done["cached"] is False
    assert done["latency_ms"] >= 0
    assert done["reflection"] == FIXED_REFLECTION
    assert done["message_id"] > 0
