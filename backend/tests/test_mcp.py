"""MCP 服务器测试：工具注册、参数 schema、降级行为（不依赖 Qdrant / 真实 LLM）。"""
import json

from app.mcp import server as mcp_module

EXPECTED_TOOLS = ["kb_search", "kb_ask", "kb_agent", "kb_stats", "kb_documents"]


async def test_tools_registered():
    """5 个工具全部注册，且都有用途描述（描述供客户端模型决策，必须非空）。"""
    tools = await mcp_module.mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert names == sorted(EXPECTED_TOOLS)
    for t in tools:
        assert t.description and t.description.strip(), f"{t.name} 缺少描述"
        assert t.input_schema and t.input_schema.get("type") == "object"


async def test_kb_search_schema():
    """kb_search 参数 schema：query 必填，top_k 默认 8。"""
    tools = await mcp_module.mcp.list_tools()
    kb_search = next(t for t in tools if t.name == "kb_search")
    props = kb_search.input_schema.get("properties", {})
    assert "query" in kb_search.input_schema.get("required", [])
    assert props["top_k"]["default"] == 8


async def test_kb_search_graceful_qdrant_down(monkeypatch):
    """向量库不可用时降级为明确提示，而不是抛异常。"""

    async def _boom(*args, **kwargs):
        raise ConnectionError("qdrant is down")

    monkeypatch.setattr(mcp_module, "hybrid_retrieve", _boom)
    result = await mcp_module.kb_search("测试检索")
    assert "暂不可用" in result
    assert "qdrant is down" in result


async def test_kb_documents_empty(client):
    """空知识库返回 count=0 的合法 JSON。"""
    result = await mcp_module.kb_documents()
    data = json.loads(result)
    assert data["count"] == 0
    assert data["documents"] == []


async def test_kb_documents_filter_ready(client):
    """按状态过滤只返回对应文档（测试库为空 -> 过滤结果也为空，验证不报错）。"""
    result = await mcp_module.kb_documents(status="ready")
    data = json.loads(result)
    assert data["count"] == 0


async def test_kb_stats_qdrant_down(client):
    """Qdrant 未启动时统计仍可用（vector_store 内部已降级为 0，不抛异常）。"""
    result = await mcp_module.kb_stats()
    data = json.loads(result)
    assert data["total_documents"] >= 0
    assert data["total_chunks"] >= 0
    assert isinstance(data["vector_points"], (int, str))
