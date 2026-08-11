"""文档 / 分块响应模型。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    meta: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str
    token_count: int


class DocumentDetailOut(DocumentOut):
    chunks: list[ChunkOut] = []


class PaginatedDocuments(BaseModel):
    total: int
    items: list[DocumentOut]


class SearchRequest(BaseModel):
    query: str = "检索测试内容"
    top_k: int = 5


class CitationOut(BaseModel):
    """回答中的引用片段。"""

    chunk_id: int | None = None
    doc_id: int
    doc_name: str
    content: str
    score: float
    chunk_index: int | None = None
