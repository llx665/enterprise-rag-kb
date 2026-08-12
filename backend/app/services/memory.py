"""会话记忆滚动摘要服务。

背景：普通多轮记忆是「历史消息硬截断最近 N 条」，早期诉求会随对话变长被丢弃。
本服务把窗口之外的消息**增量压缩**进滚动摘要（DB sessions.summary 持久化），
新对话注入「更早对话摘要 + 最近 N 条原文」，既保留长程记忆又不撑爆上下文。

机制：
- `maybe_compress`：消息数超过 MEMORY_SUMMARY_TRIGGER 后，把最近窗口之外、
  且尚未折叠（id > summary_until_id）的消息并入摘要，summary_until_id 单调推进。
- `get_session_memory`：读取 (滚动摘要, 最近 MEMORY_RECENT_LIMIT 条原文)。

降级安全：所有 LLM 调用 try/except，失败保留旧摘要不阻塞对话；
Redis 可选（REDIS_URL 非空时作缓存），DB 列始终是源真相。
"""
import logging

from sqlalchemy import select

from ..config import settings
from ..models import Message
from .rag_chain import get_llm

logger = logging.getLogger(__name__)

# 摘要指令：增量更新（有旧摘要时）或首次压缩
SUMMARY_PROMPT = """你是对话记录员。下面是一段电商客服对话，可能涉及商品咨询、售后、物流、会员、优惠等内容。
请把对话压缩成 100~200 字的中文摘要，保留：
- 用户的核心诉求与需求（想买什么、预算、偏好）
- 涉及的商品型号、参数、价格、政策结论
- 已确认的结论与待办事项
不要包含寒暄、无关细节。

{existing}对话记录：
{dialogue}

请直接输出摘要文本，不要任何前缀、引号或解释。"""


def _format_dialogue(messages: list[Message]) -> str:
    """把 Message 列表格式化为可压缩的对话文本。"""
    lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "助手"
        lines.append(f"{role}：{m.content}")
    return "\n".join(lines)


async def _compress(dialogue: str, old_summary: str | None) -> str:
    """调用 LLM 压缩对话（有旧摘要时增量更新）。"""
    from langchain_core.messages import SystemMessage

    if old_summary:
        existing = (
            f"已有摘要：\n{old_summary}\n\n"
            "请基于已有摘要增量更新，把下列新对话并入其中，保持精简。\n"
        )
    else:
        existing = ""
    prompt = SUMMARY_PROMPT.format(existing=existing, dialogue=dialogue)
    resp = await get_llm().ainvoke([SystemMessage(content=prompt)])
    text = getattr(resp, "content", "") or ""
    return text.strip() or (old_summary or "")


async def maybe_compress(db, session) -> None:
    """消息数超过阈值时，把窗口外的未折叠消息并入滚动摘要。

    幂等且降级安全：summary_until_id 单调推进避免重复压缩；
    LLM 异常保留旧摘要，不抛给调用方。
    """
    messages = list(
        (
            await db.scalars(
                select(Message)
                .where(Message.session_id == session.id)
                .order_by(Message.id)
            )
        ).all()
    )
    if len(messages) <= settings.MEMORY_SUMMARY_TRIGGER:
        return
    # 窗口边界：最前 len-recent 条待折叠，尾部保留原文（recent 窗口不折叠）
    cutoff = len(messages) - settings.MEMORY_RECENT_LIMIT
    if cutoff <= 0:
        return
    to_fold = [m for m in messages[:cutoff] if m.id > (session.summary_until_id or 0)]
    if not to_fold:
        return

    try:
        new_summary = await _compress(_format_dialogue(to_fold), session.summary)
    except Exception as e:  # noqa: BLE001 —— 摘要失败不影响对话
        logger.warning("会话 %s 摘要压缩失败，保留旧摘要: %s", session.id, e)
        return

    session.summary = new_summary or session.summary
    session.summary_until_id = max(m.id for m in to_fold)
    await db.commit()


async def get_session_memory(db, session, exclude_id: int | None = None) -> tuple[str, list[dict]]:
    """返回 (滚动摘要, 最近 N 条消息原文)。

    exclude_id：排除某条消息（如当前正在回答的提问），避免当前问题混入历史。
    早期消息已折叠进摘要，这里只取最近窗口的原文，控制注入上下文的量。
    """
    query = select(Message).where(Message.session_id == session.id)
    if exclude_id is not None:
        query = query.where(Message.id != exclude_id)
    rows = await db.scalars(query.order_by(Message.id.desc()).limit(settings.MEMORY_RECENT_LIMIT))
    recent = [
        {"role": m.role, "content": m.content}
        for m in reversed(list(rows))
    ]
    return session.summary or "", recent
