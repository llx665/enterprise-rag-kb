"""文档处理服务：编排「上传 -> 解析 -> 分块 -> 向量化 -> 入库」流水线。

处理流程在后台异步执行（不阻塞用户上传请求）：
    parse(CPU密集) --线程池--> chunk --> embed(异步API) --> qdrant upsert --> 落库
"""
import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Document, DocumentChunk
from . import vector_store
from .chunker import split_text_structured
from .document_parser import CODE_LANG, parse_document
from .embedding import get_embeddings

UPLOAD_DIR = Path(settings.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_upload(content: bytes, doc_id: int, ext: str) -> str:
    """将上传文件落盘，文件名重命名为 {doc_id}.{ext}，避免中文/特殊字符风险。"""
    stored_name = f"{doc_id}.{ext}"
    (UPLOAD_DIR / stored_name).write_bytes(content)
    return stored_name


async def process_document(doc_id: int) -> None:
    """后台处理单个文档。失败时状态置为 failed 并记录原因。"""
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return
        doc.status = "processing"
        await db.commit()

        try:
            # 1. 解析（CPU 密集，放线程池避免阻塞事件循环）
            path = UPLOAD_DIR / doc.stored_name
            text = await asyncio.to_thread(parse_document, doc.filename, path)

            # 2. 分块（父子分块：子块检索、父块作 LLM 上下文；代码文件按语言顶层定义切块）
            language = CODE_LANG.get(doc.file_type) if doc.file_type else None
            chunk_items = split_text_structured(text, language=language)
            chunks = [i.child for i in chunk_items]
            if not chunks:
                raise ValueError("文档内容为空或无法提取文本")

            # 3. 向量化 + 写入向量库
            # 首次会同步加载 torch 模型（最重的操作），必须切线程池避免阻塞事件循环
            embeddings = await asyncio.to_thread(get_embeddings)
            await vector_store.ensure_collection()

            points: list[dict] = []
            batch_size = 64
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                items = chunk_items[i : i + batch_size]
                # 异步批量向量化
                vectors = await embeddings.aembed_documents(batch)
                for j, (chunk_text, vector, item) in enumerate(zip(batch, vectors, items)):
                    payload = {
                        "doc_id": doc.id,
                        "filename": doc.filename,
                        "chunk_index": i + j,
                        "content": chunk_text,
                    }
                    if settings.PARENT_CHILD_ENABLED:
                        payload["parent_content"] = item.parent
                    points.append(
                        {
                            "point_id": str(uuid.uuid4()),
                            "vector": vector,
                            "payload": payload,
                        }
                    )

            await vector_store.upsert_points(points)

            # 4. 保存 chunk 记录（用于引用溯源）
            for p in points:
                db.add(
                    DocumentChunk(
                        doc_id=doc.id,
                        chunk_index=p["payload"]["chunk_index"],
                        content=p["payload"]["content"],
                        parent_content=p["payload"].get("parent_content"),
                        token_count=len(p["payload"]["content"]),
                        qdrant_point_id=p["point_id"],
                    )
                )

            doc.status = "ready"
            doc.chunk_count = len(points)
            doc.error_message = None

        except Exception as e:
            # 处理失败：回滚本次已写入的向量，记录错误信息
            doc.status = "failed"
            doc.error_message = str(e)
            try:
                await vector_store.delete_by_doc(doc.id)
            except Exception:
                pass

        await db.commit()


async def delete_document(doc_id: int) -> None:
    """删除文档：清理向量库、分块记录、磁盘文件、数据库记录。"""
    await vector_store.delete_by_doc(doc_id)
    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc:
            # 删除磁盘文件
            stored = UPLOAD_DIR / doc.stored_name
            if stored.exists():
                stored.unlink(missing_ok=True)
            await db.delete(doc)
            await db.commit()


async def recover_interrupted() -> None:
    """启动时恢复：把上次进程中断导致的 processing 状态重置为 pending。"""
    async with SessionLocal() as db:
        result = await db.execute(
            select(Document).where(Document.status == "processing")
        )
        for doc in result.scalars():
            doc.status = "pending"
            doc.error_message = "上次处理被中断，请重新处理"
        await db.commit()


async def reprocess_document(doc_id: int) -> None:
    """重新处理单个文档（删除旧向量与分块后重新跑流水线）。"""
    await vector_store.delete_by_doc(doc_id)
    async with SessionLocal() as db:
        chunks = await db.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        )
        for c in chunks.scalars():
            await db.delete(c)
        await db.commit()
    await process_document(doc_id)
