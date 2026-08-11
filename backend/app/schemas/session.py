"""会话响应模型。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime


class PaginatedSessions(BaseModel):
    total: int
    items: list[SessionOut]


class RenameRequest(BaseModel):
    title: str
