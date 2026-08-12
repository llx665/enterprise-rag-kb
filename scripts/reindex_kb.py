"""重建知识库索引：对所有 ready 文档重新执行处理流水线（父子分块生效）。

场景：代码升级了分块策略（如引入父子分块）后，旧库的 chunk 只有 content、没有
parent_content。跑本脚本会对每个 ready 文档调用 reprocess_document —— 删除旧向量
与旧分块，按新策略重新分块/向量化/落库，完成后清空语义缓存。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/reindex_kb.py
"""
import asyncio
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 以脚本自身位置推导 backend/，避免 cwd 依赖（scripts/ 与 backend/ 同级）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))


async def main() -> None:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Document
    from app.services.cache import get_cache
    from app.services.document_service import reprocess_document

    async with SessionLocal() as db:
        docs = await db.scalars(
            select(Document).where(Document.status == "ready").order_by(Document.id)
        )
        ready = list(docs.all())

    print(f"待重建索引的文档：{len(ready)} 个")
    for doc in ready:
        print(f"  - [{doc.id}] {doc.filename}", end="", flush=True)
        try:
            await reprocess_document(doc.id)
            async with SessionLocal() as db:
                refreshed = await db.get(Document, doc.id)
                print(f" ✅ ready（块数: {refreshed.chunk_count}）")
        except Exception as e:  # noqa: BLE001
            print(f" ❌ 失败: {e}")

    # 分块内容已变，旧缓存全部作废
    await get_cache().clear()
    print("\n完成。语义缓存已清空。")


if __name__ == "__main__":
    asyncio.run(main())
