"""知识库管理接口（仅管理员可访问）。

- 上传文档 -> 异步解析/分块/向量化
- 文档列表 / 详情 / 删除 / 重建索引
- 知识库统计
- 检索测试（预览命中片段，便于调试与评估）
"""
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select

from ..config import settings
from ..core.deps import AdminUser, DbDep
from ..models import Document, DocumentChunk
from ..schemas.document import (
    DocumentDetailOut,
    DocumentOut,
    PaginatedDocuments,
    SearchRequest,
)
from ..services import task_manager, vector_store
from ..services.cache import get_cache
from ..services.document_parser import SUPPORTED_EXTS
from ..services.document_service import delete_document, save_upload

router = APIRouter(prefix="/kb", tags=["知识库"])


@router.post("/documents", response_model=DocumentOut, status_code=201, summary="上传文档")
async def upload_document(
    db: DbDep,
    admin: AdminUser,
    file: UploadFile = File(...),
    description: str = Form(default=""),
):
    filename = file.filename or "unnamed"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 .{ext}，支持：{', '.join(sorted(SUPPORTED_EXTS))}",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过大小限制（{settings.MAX_UPLOAD_SIZE_MB}MB）",
        )

    doc = Document(
        filename=filename,
        stored_name="",  # 落盘后回填
        file_type=ext,
        file_size=len(content),
        status="pending",
        uploaded_by=admin.id,
        meta={"description": description} if description else None,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    doc.stored_name = save_upload(content, doc.id, ext)
    await db.commit()
    # onupdate 触发的 updated_at 已过期，刷新一次避免异步惰性加载报错
    await db.refresh(doc)

    # 知识库内容变化 → 作废语义缓存，避免旧答案带错误/过时引用
    await get_cache().clear()

    # 异步后台处理，立即返回，不阻塞上传请求
    task_manager.submit_document(doc.id)
    return doc


@router.get("/documents", response_model=PaginatedDocuments, summary="文档列表")
async def list_documents(
    db: DbDep,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
):
    base = select(Document)
    if status:
        base = base.where(Document.status == status)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    docs = await db.scalars(
        base.order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedDocuments(total=total or 0, items=list(docs))


@router.get("/documents/{doc_id}", response_model=DocumentDetailOut, summary="文档详情")
async def get_document(doc_id: int, db: DbDep, admin: AdminUser):
    from sqlalchemy.orm import selectinload

    # selectinload 预加载 chunks，避免异步惰性加载（MissingGreenlet）
    doc = await db.scalar(
        select(Document)
        .where(Document.id == doc_id)
        .options(selectinload(Document.chunks))
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.delete("/documents/{doc_id}", summary="删除文档")
async def remove_document(doc_id: int, db: DbDep, admin: AdminUser):
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    await delete_document(doc_id)
    # 文档删除后，引用它的缓存回答全部作废
    await get_cache().clear()
    return {"message": "文档已删除"}


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut, summary="重新处理文档")
async def reindex_document(doc_id: int, db: DbDep, admin: AdminUser):
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 清空旧向量与分块后重新处理
    from ..services import document_service

    await document_service.reprocess_document(doc_id)
    # 内容已重写，旧缓存作废
    await get_cache().clear()
    await db.refresh(doc)
    return doc


@router.get("/stats", summary="知识库统计")
async def stats(db: DbDep, admin: AdminUser):
    total_docs = await db.scalar(
        select(func.count()).select_from(Document)
    )
    ready_docs = await db.scalar(
        select(func.count()).select_from(Document).where(Document.status == "ready")
    )
    total_chunks = await db.scalar(
        select(func.count()).select_from(DocumentChunk)
    )
    vector_count = await vector_store.count_points()
    return {
        "total_documents": total_docs or 0,
        "ready_documents": ready_docs or 0,
        "total_chunks": total_chunks or 0,
        "vector_points": vector_count,
    }


@router.post("/search", summary="检索测试（管理员调试用）")
async def test_search(data: SearchRequest, db: DbDep, admin: AdminUser):
    """混合检索测试：稠密向量 + jieba/BM25 + RRF 融合，返回命中片段与相似度。"""
    from ..services.retriever import hybrid_retrieve

    hits = await hybrid_retrieve(data.query, top_k=data.top_k)
    return [
        {
            "doc_id": h["doc_id"],
            "doc_name": h["doc_name"],
            "content": h["content"],
            "score": round(h["score"], 4),
            "chunk_index": h["chunk_index"],
        }
        for h in hits
    ]
