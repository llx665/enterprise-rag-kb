"""会话表：每个用户拥有多个独立会话。

滚动摘要记忆：summary 保存更早对话的压缩摘要，summary_until_id 记录摘要折叠到哪条消息。
二者在历史超过 MEMORY_SUMMARY_TRIGGER 条后被 memory.maybe_compress 更新，
保证超长会话不因「20 条硬截断」丢失早期诉求。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    # 滚动摘要：折叠后的早期对话记忆（可空，未压缩时为空）
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 摘要已折叠到的消息 ID 上限（< 该值的消息已并入 summary，不再加载）
    summary_until_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # 最后消息时间，用于会话列表按活跃度排序
    last_message_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="sessions")  # noqa: F821
    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )
