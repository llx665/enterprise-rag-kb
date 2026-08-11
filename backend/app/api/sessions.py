"""会话管理接口：多用户多会话、历史记录持久化、标题管理与搜索。

每个用户只能访问自己的会话（user_id 鉴权）。
"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from ..core.deps import CurrentUser, DbDep
from ..models import ChatSession, Message
from ..schemas.message import MessageOut
from ..schemas.session import PaginatedSessions, RenameRequest, SessionOut

router = APIRouter(prefix="/sessions", tags=["会话"])


@router.get("", response_model=PaginatedSessions, summary="会话列表")
async def list_sessions(
    user: CurrentUser,
    db: DbDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(None, description="按标题搜索"),
):
    base = select(ChatSession).where(ChatSession.user_id == user.id)
    if keyword:
        base = base.where(ChatSession.title.ilike(f"%{keyword}%"))

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    sessions = await db.scalars(
        base.order_by(ChatSession.last_message_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedSessions(total=total or 0, items=list(sessions))


@router.post("", response_model=SessionOut, status_code=201, summary="新建会话")
async def create_session(user: CurrentUser, db: DbDep):
    session = ChatSession(user_id=user.id, title="新对话")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}/messages", response_model=list[MessageOut], summary="会话消息历史")
async def get_messages(session_id: int, user: CurrentUser, db: DbDep):
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = await db.scalars(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.asc())
    )
    return list(messages)


@router.put("/{session_id}", response_model=SessionOut, summary="重命名会话")
async def rename_session(
    session_id: int,
    payload: RenameRequest,
    user: CurrentUser,
    db: DbDep,
):
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    session.title = title[:100]
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", summary="删除会话")
async def delete_session(session_id: int, user: CurrentUser, db: DbDep):
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(session)  # 级联删除消息
    await db.commit()
    return {"message": "会话已删除"}
