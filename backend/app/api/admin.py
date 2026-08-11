"""管理员仪表盘接口（数据看板 / 反馈 / RAG 评估指标）。

数据看板聚合四类指标：
- 用户与会话：注册用户数、会话数
- 问答规模与质量：问答次数、平均生成延迟、语义缓存命中率
- 反馈闭环：好评/差评数、好评率、最近反馈明细
- 知识库规模：文档数、分块数
- 近 7 天趋势：每日问答量、新增用户、平均延迟、缓存命中（前端折线图）
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from ..core.deps import AdminUser, DbDep
from ..models import ChatSession, Document, DocumentChunk, Message, User
from ..services.cache import get_cache

router = APIRouter(prefix="/admin", tags=["管理后台"])


@router.post("/cache/clear", summary="清空语义缓存")
async def clear_cache(admin: AdminUser):
    """知识库内容变更后手动作废语义缓存，避免返回过期回答。"""
    n = await get_cache().clear()
    return {"message": f"已清空 {n} 条语义缓存"}


def _ratio(num, den):
    return round(num / den, 4) if den else 0.0


@router.get("/dashboard", summary="数据看板统计")
async def dashboard(db: DbDep, admin: AdminUser):
    # ---------- 1. 总览统计 ----------
    total_users = await db.scalar(select(func.count()).select_from(User))
    total_sessions = await db.scalar(select(func.count()).select_from(ChatSession))
    total_questions = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == "user")
    )
    total_answers = await db.scalar(
        select(func.count()).select_from(Message).where(Message.role == "assistant")
    )
    avg_latency = await db.scalar(
        select(func.avg(Message.latency_ms)).where(Message.role == "assistant")
    )
    cache_hits = await db.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.role == "assistant", Message.cached.is_(True))
    )
    good = await db.scalar(
        select(func.count()).select_from(Message).where(Message.feedback == "up")
    )
    bad = await db.scalar(
        select(func.count()).select_from(Message).where(Message.feedback == "down")
    )
    total_docs = await db.scalar(select(func.count()).select_from(Document))
    total_chunks = await db.scalar(select(func.count()).select_from(DocumentChunk))

    # ---------- 2. 近 7 天趋势（Python 侧按天聚合，跨 SQLite/PostgreSQL 兼容） ----------
    today = date.today()
    day_keys = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    since = datetime.combine(today - timedelta(days=6), datetime.min.time())

    questions_day = {k: 0 for k in day_keys}
    answers_day = {k: 0 for k in day_keys}
    cache_hits_day = {k: 0 for k in day_keys}
    latency_day = {k: 0 for k in day_keys}
    users_day = {k: 0 for k in day_keys}

    messages = await db.scalars(select(Message).where(Message.created_at >= since))
    for m in messages:
        dk = m.created_at.date().isoformat()
        if dk not in questions_day:
            continue
        if m.role == "user":
            questions_day[dk] += 1
        else:
            answers_day[dk] += 1
            if m.cached:
                cache_hits_day[dk] += 1
            if m.latency_ms:
                latency_day[dk] += m.latency_ms

    new_users = await db.scalars(select(User).where(User.created_at >= since))
    for u in new_users:
        dk = u.created_at.date().isoformat()
        if dk in users_day:
            users_day[dk] += 1

    return {
        "stats": {
            "total_users": total_users or 0,
            "total_sessions": total_sessions or 0,
            "total_questions": total_questions or 0,
            "total_answers": total_answers or 0,
            "avg_latency_ms": round(avg_latency) if avg_latency else 0,
            # RAG 评估指标：缓存命中率 / 好评率
            "cache_hit_rate": _ratio(cache_hits or 0, total_answers or 0),
            "good_feedback": good or 0,
            "bad_feedback": bad or 0,
            "satisfaction_rate": _ratio(good or 0, (good or 0) + (bad or 0)),
            "total_documents": total_docs or 0,
            "total_chunks": total_chunks or 0,
        },
        "trends": {
            "dates": day_keys,
            "questions": [questions_day[k] for k in day_keys],
            "new_users": [users_day[k] for k in day_keys],
            "avg_latency_ms": [
                round(latency_day[k] / answers_day[k]) if answers_day[k] else 0
                for k in day_keys
            ],
            "cache_hits": [cache_hits_day[k] for k in day_keys],
        },
    }


@router.get("/feedback", summary="答案反馈列表")
async def feedback_list(
    db: DbDep,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """已反馈（好评/差评）的问答记录，含用户与会话上下文。"""
    base = select(Message).where(Message.feedback.is_not(None))

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    )
    rows = await db.scalars(
        base.options(joinedload(Message.session).joinedload(ChatSession.user))
        .order_by(Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for m in rows:
        user_name = m.session.user.username if m.session and m.session.user else "?"
        # 反馈消息 1 分钟内的上一条提问即为触发它的原问题
        prev = await db.scalar(
            select(Message.content)
            .where(
                Message.session_id == m.session_id,
                Message.role == "user",
                Message.id < m.id,
            )
            .order_by(Message.id.desc())
            .limit(1)
        )
        items.append(
            {
                "message_id": m.id,
                "feedback": m.feedback,
                "answer": m.content,
                "question": prev or "",
                "username": user_name,
                "session_id": m.session_id,
                "created_at": m.created_at.isoformat(),
            }
        )
    return {"total": total or 0, "items": items}
