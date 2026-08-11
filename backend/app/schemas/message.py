"""消息 / 问答请求响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    citations: list[dict[str, Any]] | None = None
    feedback: str | None = None
    latency_ms: int | None = None
    cached: bool = False
    created_at: datetime


class ChatRequest(BaseModel):
    """问答请求：可指定会话，不指定则自动创建新会话。"""

    session_id: int | None = None
    question: str = Field(min_length=1, max_length=4000, description="用户问题")
