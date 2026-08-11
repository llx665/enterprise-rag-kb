"""RAG 问答链路：检索 -> 组装上下文 -> LLM 生成（支持流式）。

回答要求模型基于知识库内容作答，并在句末标注 [序号] 引用，
引用元数据（来源文档/原文/相似度）随 SSE 事件一并返回给前端渲染。
"""
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..config import settings
from .embedding import get_embeddings
from .retriever import hybrid_retrieve

SYSTEM_PROMPT = """你是「电商知识库问答助手」，专门基于提供的知识库资料回答用户关于商品的问题。

回答要求：
1. 优先使用知识库资料中的信息作答，引用资料内容时在句末标注 [序号]，序号对应下方「参考资料」的编号。可以引用多条。
2. 如果资料中完全没有相关信息，如实说明"知识库中暂无相关信息"，不要编造或猜测。
3. 回答使用中文，简洁、准确、条理清晰；涉及参数、价格、规格时尽量具体。
4. 若用户问题与商品/知识库无关，礼貌地引导其回到商品咨询主题。

参考资料：
{context}
"""


@lru_cache
def get_llm() -> ChatOpenAI:
    """全局 LLM 客户端（DeepSeek，OpenAI 兼容接口）。"""
    if not settings.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 backend/.env 中填写")
    return ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=settings.LLM_TEMPERATURE,
        streaming=True,
        max_tokens=2048,
    )


async def retrieve(
    query: str,
    top_k: int | None = None,
    vector: list[float] | None = None,
) -> list[dict]:
    """混合检索：稠密向量（Qdrant）+ 稀疏关键词（jieba+BM25）→ RRF 融合。

    vector 参数可传入预计算的 query 向量（语义缓存已算过时复用，避免重复 embed）。
    返回 dict 形式命中：[{doc_id, doc_name, chunk_index, content, score}]
    """
    return await hybrid_retrieve(query, top_k=top_k, vector=vector)


def hits_to_citations(hits: list[dict]) -> list[dict]:
    """把检索命中转换为引用元数据（含原文与相似度）。"""
    return [
        {
            "doc_id": h.get("doc_id"),
            "doc_name": h.get("doc_name", ""),
            "chunk_index": h.get("chunk_index", 0),
            "content": h.get("content", ""),
            "score": round(h.get("score", 0), 4),
        }
        for h in hits
    ]


def format_context(hits: list[dict]) -> str:
    """把检索命中的片段格式化为带编号的参考资料。"""
    lines = []
    for i, h in enumerate(hits, start=1):
        source = h.get("doc_name", "未知来源")
        content = h.get("content", "").strip()
        lines.append(f"[{i}] 来源：{source}\n{content}")
    return "\n\n".join(lines)


def build_messages(
    question: str,
    history: list[dict[str, Any]],
    context: str,
) -> list:
    """组装对话消息：系统提示 + 历史对话 + 当前问题。"""
    messages: list = [SystemMessage(content=SYSTEM_PROMPT.format(context=context))]
    # 历史对话（最近的若干轮），保持多轮语境
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=question))
    return messages
