"""问答接口：RAG 检索增强生成 + Agent 工具调用，SSE 流式返回。

SSE 事件协议：
  event: meta    -> {"citations": [...]}   引用元数据（渲染引用标注用）
  event: tool    -> {"name", "display"}    工具调用状态（Agent 路径，供前端展示“正在查询天气…”）
  event: delta   -> {"content": "..."}     回答增量文本
  event: done    -> {"message_id", "session_id", "title", "latency_ms", "cached"}  完成
  event: error   -> {"detail": "..."}      出错

双链路路由（router.is_tool_intent）：
  - 商品/知识库问题 → RAG 链路：语义缓存 + 混合检索 + 引用标注
  - 计算/天气/日历等 → Agent 链路：LangGraph Agent 调用工具（计算器/天气/农历日历/检索）
    工具类问题跳过语义缓存，避免“2+2”与“2+3”误命中缓存答案

性能优化集成：
  - 语义缓存：相似问题直接返回缓存回答（省一次 LLM 调用）
  - 混合检索：稠密向量 + jieba/BM25 + RRF 融合（在 rag_chain.retrieve 内）
  - 接口限流：防止恶意刷接口耗尽 DeepSeek 配额
"""
import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..config import settings
from ..core.deps import CurrentUser, DbDep
from ..core.limiter import limiter
from ..models import ChatSession, Message
from ..schemas.message import ChatRequest
from ..services import rag_chain
from ..services.agent import format_tool_display, stream_agent
from ..services.cache import get_cache
from ..services.embedding import get_embeddings
from ..services.router import is_tool_intent

router = APIRouter(prefix="/chat", tags=["问答"])

# 拼入上下文的历史消息条数上限（多轮记忆，同时避免上下文过长）
HISTORY_LIMIT = 20


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class FeedbackRequest(BaseModel):
    message_id: int
    feedback: str = Field(description="up / down")


@router.post("/feedback", summary="提交答案反馈")
@limiter.limit("60/minute")
async def submit_feedback(request: Request, req: FeedbackRequest, user: CurrentUser, db: DbDep):
    msg = await db.get(Message, req.message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    # 校验归属：只能反馈自己会话中的消息
    session = await db.get(ChatSession, msg.session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该消息")
    if req.feedback not in ("up", "down"):
        raise HTTPException(status_code=400, detail="feedback 取值只能是 up / down")

    msg.feedback = req.feedback
    await db.commit()
    return {"feedback": msg.feedback}


@router.post("", summary="发起问答（SSE 流式返回）")
@limiter.limit("20/minute")
async def chat(request: Request, req: ChatRequest, user: CurrentUser, db: DbDep):
    # ---------- 1. 解析 / 创建会话 ----------
    if req.session_id is None:
        session = ChatSession(user_id=user.id, title="新对话")
        db.add(session)
        await db.commit()
        await db.refresh(session)
    else:
        session = await db.get(ChatSession, req.session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")

    # ---------- 2. 保存用户提问 ----------
    user_msg = Message(session_id=session.id, role="user", content=req.question)
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # ---------- 3. 加载历史（排除刚保存的当前提问） ----------
    history_rows = await db.scalars(
        select(Message)
        .where(Message.session_id == session.id, Message.id < user_msg.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_LIMIT)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(list(history_rows))
    ]

    async def save_answer(
        content: str, citations: list, latency_ms: int, cached: bool = False
    ) -> Message:
        """保存助手回答，并自动生成会话标题、刷新活跃时间。"""
        assistant_msg = Message(
            session_id=session.id,
            role="assistant",
            content=content,
            citations=citations,
            latency_ms=latency_ms,
            cached=cached,
        )
        db.add(assistant_msg)
        # 首次提问时自动生成会话标题（截取问题前 20 字）
        if session.title == "新对话":
            session.title = req.question[:20] + ("…" if len(req.question) > 20 else "")
        session.last_message_at = await db.scalar(func.now())
        await db.commit()
        await db.refresh(assistant_msg)
        return assistant_msg

    async def event_generator():
        try:
            # ---------- 3.4 意图路由：工具类问题走 Agent，其余走 RAG ----------
            # 工具类问题（计算/天气/日历）跳过语义缓存，避免“2+2”与“2+3”这类
            # 向量相近但答案不同的问题误命中缓存。
            if is_tool_intent(req.question):
                content_parts: list[str] = []
                start = time.perf_counter()
                async for ev in stream_agent(req.question, history):
                    if ev["type"] == "tool":
                        # 工具调用前的模型过渡文字不是最终答案，丢弃重来
                        content_parts.clear()
                        yield _sse(
                            "tool",
                            {
                                "name": ev["name"],
                                "display": format_tool_display(ev["name"], ev["args"]),
                            },
                        )
                    else:
                        content_parts.append(ev["content"])
                        yield _sse("delta", {"content": ev["content"]})
                latency_ms = int((time.perf_counter() - start) * 1000)
                answer = "".join(content_parts).strip()
                if not answer:
                    answer = "抱歉，我暂时无法处理该问题。"
                assistant_msg = await save_answer(answer, [], latency_ms)
                yield _sse(
                    "done",
                    {
                        "message_id": assistant_msg.id,
                        "session_id": session.id,
                        "title": session.title,
                        "latency_ms": latency_ms,
                        "cached": False,
                    },
                )
                return

            # ---------- 3.5 语义缓存（仅 RAG 链路）----------
            # 先计算 query 向量：缓存命中则直接复用，未命中则传给混合检索复用，只 embed 一次
            qvec = await get_embeddings().aembed_query(req.question)
            cached = None
            if settings.CACHE_ENABLED:
                try:
                    cached = await get_cache().get(qvec)
                except Exception:
                    cached = None  # Redis 异常时降级为正常检索

            if cached:
                answer, citations = cached
                yield _sse("meta", {"citations": citations})
                # 缓存命中：按 20 字符切块流式推送，前端体验与实时生成一致
                for i in range(0, len(answer), 20):
                    yield _sse("delta", {"content": answer[i : i + 20]})
                assistant_msg = await save_answer(answer, citations, 0, cached=True)
                yield _sse(
                    "done",
                    {
                        "message_id": assistant_msg.id,
                        "session_id": session.id,
                        "title": session.title,
                        "latency_ms": 0,
                        "cached": True,  # 前端可展示"命中缓存"标识
                    },
                )
                return

            # ---------- 4. 混合检索 + LLM 生成 ----------
            hits = await rag_chain.retrieve(req.question, vector=qvec)
            citations = rag_chain.hits_to_citations(hits)
            context = rag_chain.format_context(hits)
            messages = rag_chain.build_messages(req.question, history, context)

            # 先推送引用元数据，前端据此渲染引用锚点
            yield _sse("meta", {"citations": citations})

            content_parts: list[str] = []
            start = time.perf_counter()
            async for chunk in rag_chain.get_llm().astream(messages):
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield _sse("delta", {"content": chunk.content})
            latency_ms = int((time.perf_counter() - start) * 1000)

            answer = "".join(content_parts)
            assistant_msg = await save_answer(answer, citations, latency_ms)

            # ---------- 5. 写入语义缓存（失败不影响主流程） ----------
            if settings.CACHE_ENABLED:
                try:
                    await get_cache().set(qvec, req.question, answer, citations)
                except Exception:
                    pass

            yield _sse(
                "done",
                {
                    "message_id": assistant_msg.id,
                    "session_id": session.id,
                    "title": session.title,
                    "latency_ms": latency_ms,
                    "cached": False,
                },
            )

        except Exception as e:
            # 生成出错：兜底返回错误事件，前端展示
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证流式实时性
        },
    )
