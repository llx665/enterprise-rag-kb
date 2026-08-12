"""文档处理流水线测试：父子分块时 Qdrant payload 与 DB 列都写入 parent_content。"""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document, User
from app.services import document_service, vector_store

MD_DOC = """# 手机 X1 Pro

## 参数

支持 100W 有线快充，5000mAh 电池。
"""


class _FakeEmbeddings:
    """embedding 桩：返回定长向量，模拟 aembed_documents / aembed_query。"""

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 512 for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return [0.1] * 512


@pytest.fixture
def captured_points(monkeypatch):
    """桩化 embedding 与向量写入，捕获 upsert 的 points。"""
    points: list[dict] = []

    async def _fake_upsert(points_: list[dict]) -> None:
        points.extend(points_)

    monkeypatch.setattr(document_service, "get_embeddings", lambda: _FakeEmbeddings())
    monkeypatch.setattr(vector_store, "upsert_points", _fake_upsert)
    return points


async def _create_doc(filename: str, stored_name: str, file_type: str, content: str) -> int:
    """创建一条 uploaded_by=admin 的文档记录（stored_name 指向真实文件）。"""
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == "admin"))
        doc = Document(
            filename=filename,
            stored_name=stored_name,
            file_type=file_type,
            file_size=len(content.encode()),
            status="pending",
            uploaded_by=admin.id,
        )
        db.add(doc)
        await db.commit()
        return doc.id


@pytest.mark.asyncio
async def test_structured_pipeline_writes_parent_content(client, captured_points):
    """处理 .md 文档：payload 与 DB 行都带 parent_content。"""
    (document_service.UPLOAD_DIR / "test_structured.md").write_text(MD_DOC, encoding="utf-8")
    doc_id = await _create_doc("商品.md", "test_structured.md", "md", MD_DOC)

    await document_service.process_document(doc_id)

    # Qdrant payload
    assert captured_points, "应产生至少一个向量点"
    for p in captured_points:
        assert p["payload"]["parent_content"], "payload 必须带父块全文"

    # DB 行（selectinload 预加载 chunks，避免 async 懒加载 MissingGreenlet）
    from sqlalchemy.orm import selectinload

    async with SessionLocal() as db:
        doc = await db.scalar(
            select(Document)
            .where(Document.id == doc_id)
            .options(selectinload(Document.chunks))
        )
        assert doc.status == "ready"
        assert doc.chunk_count == len(captured_points)
        assert doc.chunks and all(c.parent_content for c in doc.chunks)

    # 清理：删除测试文档与文件，避免污染后续测试
    await document_service.delete_document(doc_id)
    (document_service.UPLOAD_DIR / "test_structured.md").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_structured_pipeline_code_file(client, captured_points):
    """处理 .py 代码文件：按顶层定义切块，parent_content 含 class 定义。"""
    code = (
        "# 订单模块\n\n"
        "class OrderService:\n"
        "    def create_order(self):\n"
        "        return {'ok': True}\n\n"
        "def pay_order(order_no):\n"
        "    return order_no\n"
    )
    (document_service.UPLOAD_DIR / "test_code.py").write_text(code, encoding="utf-8")
    doc_id = await _create_doc("订单模块.py", "test_code.py", "py", code)

    await document_service.process_document(doc_id)

    assert captured_points
    # 代码块父块以 class/def 开头
    assert any(
        p["payload"]["parent_content"].lstrip().startswith("class OrderService")
        for p in captured_points
    )

    async with SessionLocal() as db:
        doc = await db.get(Document, doc_id)
        assert doc.status == "ready"
        assert doc.chunk_count == len(captured_points)

    await document_service.delete_document(doc_id)
    (document_service.UPLOAD_DIR / "test_code.py").unlink(missing_ok=True)
