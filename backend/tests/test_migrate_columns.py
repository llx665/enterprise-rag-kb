"""迁移测试：运行 create_all + migrate 后，新列存在于表中（父块全文 / 会话摘要）。"""
import sqlite3

import pytest

from app.database import engine

NEW_COLUMNS = {
    "document_chunks": ["parent_content"],
    "sessions": ["summary", "summary_until_id"],
}


@pytest.fixture(scope="module")
def migrated_db():
    """执行 create_all + migrate，返回连接（与 main.lifespan 相同路径）。"""
    import asyncio

    from app.database import Base
    from app.main import migrate

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await migrate()

    asyncio.get_event_loop_policy().new_event_loop()
    asyncio.run(_setup())
    return engine


def _columns(db_path: str, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {r[1] for r in rows}
    finally:
        conn.close()


def test_new_columns_exist(migrated_db):
    """每次迁移后，所有新增列都存在（幂等，重复跑不报错）。"""
    url = str(engine.url)
    db_path = url.split("///")[-1]
    for table, cols in NEW_COLUMNS.items():
        present = _columns(db_path, table)
        for col in cols:
            assert col in present, f"{table}.{col} 列缺失"


def test_migrate_idempotent(migrated_db):
    """migrate 重复执行不抛异常（SQLite 无 IF NOT EXISTS，靠 try/except 吞）。"""
    import asyncio

    from app.main import migrate

    async def _again():
        await migrate()

    asyncio.run(_again())
