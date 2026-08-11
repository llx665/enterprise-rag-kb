"""消息表：会话内的对话记录。

citations 字段（JSON）保存回答引用的知识库片段：
[{"chunk_id": 1, "doc_id": 2, "doc_name": "xxx.pdf", "content": "原文", "score": 0.87}, ...]
这是前端渲染「引用标注」的数据来源。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 角色：user（用户提问）/ assistant（模型回答）
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 引用的知识库片段列表，assistant 消息才有
    citations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    # 用户反馈：up / down / None
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 生成耗时（毫秒），用于性能监控
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 是否命中语义缓存（True 表示回答来自缓存，未调用 LLM；性能优化指标）
    cached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="messages")  # noqa: F821
