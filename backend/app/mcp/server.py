"""MCP 服务器：把 RAG 知识库问答能力暴露为 MCP 工具。

设计原则：**只复用、不重写** —— 所有工具都直接调用现有服务
（retriever / rag_chain / agent / router / database），
与 REST API（/api/chat、/api/kb）共用同一套检索、生成与存储逻辑，
因此工具返回的结果与网页端口径完全一致。

暴露工具（5 个）：
- kb_search     混合检索知识库，返回带来源文档与相似度的命中片段（低层能力）
- kb_ask        知识库 RAG 问答：检索 + LLM 生成，返回答案与引用（高层一步到位）
- kb_agent      通用 AI 助手：意图路由，计算 / 天气 / 日历 / 知识库（Agent + RAG）
- kb_stats      知识库统计：文档数 / 就绪数 / 分块数 / 向量点数
- kb_documents  知识库文档列表（可按状态过滤）

运输方式（由 `backend/run_mcp_server.py` 提供入口）：
- stdio：本机直连（Claude Code .mcp.json / Claude Desktop 配置）
- Streamable HTTP：`python run_mcp_server.py --transport http`

安全：工具只读（检索 / 问答 / 统计），不暴露写入、删除、管理能力；
HTTP 模式可选 `MCP_HTTP_TOKEN` 鉴权（见 config.py）。
"""
import json

from sqlalchemy import func, select

from ..config import settings
from ..database import SessionLocal
from ..models import Document, DocumentChunk
from ..services import rag_chain, vector_store
from ..services.agent import stream_agent
from ..services.retriever import hybrid_retrieve

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    raise SystemExit(
        "未安装 MCP SDK。请先安装后端依赖："
        "backend/.venv/Scripts/pip install -r backend/requirements.txt"
    )

mcp = MCPServer(
    settings.MCP_SERVER_NAME,
    title="企业级 RAG 知识库",
    description="基于 LangChain 的企业级 RAG 知识库问答系统（MCP 接口）",
    instructions=(
        "本服务器把知识库问答系统暴露为 MCP 工具。\n"
        "1. 用户询问知识库内容（商品参数/价格/型号/售后/物流/会员/优惠等）时，"
        "优先用 kb_ask 一步获得带引用的答案；需要自行核对原文时用 kb_search 检索命中片段。\n"
        "2. 涉及数学计算/实时天气/日历农历等通用能力时，用 kb_agent（内置意图路由）。\n"
        "3. 了解知识库状态用 kb_stats / kb_documents。\n"
        "4. 所有工具均为只读，不会修改知识库。"
    ),
    version="1.0.0",
)


# ==========================================================
# 工具：检索 / 问答 / 助手 / 统计 / 文档
# ==========================================================
@mcp.tool()
async def kb_search(query: str, top_k: int = 8) -> str:
    """混合检索知识库，返回命中的原文片段、来源文档、分块序号与相似度。用于需要核对原文或自行组织回答的场景。"""
    try:
        hits = await hybrid_retrieve(query, top_k=max(1, min(int(top_k), 20)))
    except Exception as e:  # noqa: BLE001 —— 向量库/模型不可用时降级为明确提示
        return f"知识库检索暂不可用：{e.__class__.__name__}: {e}"
    return json.dumps(
        {
            "query": query,
            "count": len(hits),
            "hits": [
                {
                    "doc_id": h.get("doc_id"),
                    "doc_name": h.get("doc_name", ""),
                    "chunk_index": h.get("chunk_index", 0),
                    "score": round(h.get("score", 0), 4),
                    "content": h.get("content", ""),
                }
                for h in hits
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def kb_ask(question: str) -> str:
    """基于知识库回答问题（RAG + Self-RAG 自省）：混合检索 + 生成 + 事实核对，返回答案、引用来源与自省信息。适合直接给出最终答复。"""
    try:
        from ..services.self_rag import self_rag_answer

        hits = await rag_chain.retrieve(question)
        answer, reflection = await self_rag_answer(question, [], hits)
        answer = answer.strip() or "知识库中暂无相关信息。"
    except Exception as e:  # noqa: BLE001
        return f"知识库问答暂不可用：{e.__class__.__name__}: {e}"
    citations = rag_chain.hits_to_citations(hits)
    return json.dumps(
        {
            "question": question,
            "answer": answer,
            "citations": citations,
            "reflection": reflection,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def kb_agent(question: str) -> str:
    """通用 AI 助手：按意图路由到 Agent（数学计算 / 实时天气 / 日历农历 / 知识库检索）。适合非知识库类的通用问题。"""
    try:
        parts: list[str] = []
        async for ev in stream_agent(question, []):
            if ev["type"] == "token":
                parts.append(ev["content"])
        answer = "".join(parts).strip()
    except Exception as e:  # noqa: BLE001
        return f"AI 助手暂不可用：{e.__class__.__name__}: {e}"
    return answer or "抱歉，我暂时无法处理该问题。"


@mcp.tool()
async def kb_stats() -> str:
    """返回知识库统计信息：文档总数、已就绪文档数、分块总数、向量点数量。"""
    try:
        async with SessionLocal() as db:
            total = await db.scalar(select(func.count()).select_from(Document)) or 0
            ready = await db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "ready")
            ) or 0
            chunks = await db.scalar(select(func.count()).select_from(DocumentChunk)) or 0
    except Exception as e:  # noqa: BLE001
        return f"知识库统计暂不可用：{e.__class__.__name__}: {e}"
    try:
        vectors = await vector_store.count_points()
    except Exception as e:  # noqa: BLE001 —— Qdrant 未启动时该项降级展示
        vectors = f"不可用（{e.__class__.__name__}）"
    return json.dumps(
        {
            "total_documents": total,
            "ready_documents": ready,
            "total_chunks": chunks,
            "vector_points": vectors,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def kb_documents(status: str = "") -> str:
    """返回知识库文档列表。status 可选过滤值：pending / processing / ready / failed，留空返回全部。"""
    try:
        async with SessionLocal() as db:
            base = select(Document)
            if status:
                base = base.where(Document.status == status)
            docs = await db.scalars(base.order_by(Document.created_at.desc()))
            items = [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "status": d.status,
                    "chunk_count": d.chunk_count,
                    "created_at": str(d.created_at),
                }
                for d in docs
            ]
    except Exception as e:  # noqa: BLE001
        return f"文档列表暂不可用：{e.__class__.__name__}: {e}"
    return json.dumps({"count": len(items), "documents": items}, ensure_ascii=False, indent=2)


# 工具名单（供测试与文档引用，避免魔法字符串散落）
TOOL_NAMES = ["kb_search", "kb_ask", "kb_agent", "kb_stats", "kb_documents"]
