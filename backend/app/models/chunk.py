"""文档分块表：记录每个 chunk 的原文与 Qdrant 点位映射。

这是「引用溯源」的关键 —— 回答中标注的引用片段，
通过 doc_id / qdrant_point_id 能精确回到原文和来源文档。
"""
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 在文档内的分块序号
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 父块全文（父子分块：子块检索、父块作 LLM 上下文）。旧块为 NULL，检索时回退 content
    parent_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # 对应的 Qdrant 向量点位 ID（向量库中的唯一标识）
    qdrant_point_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")  # noqa: F821
