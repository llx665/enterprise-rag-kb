"""数据库引擎与会话管理（异步 SQLAlchemy 2.0）。

本地开发默认 SQLite（aiosqlite），生产环境切换为 PostgreSQL（asyncpg），
只需修改 DATABASE_URL 环境变量，无需改动代码。
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供数据库会话，请求结束自动关闭。"""
    async with SessionLocal() as session:
        yield session
