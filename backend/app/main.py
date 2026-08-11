"""应用入口：FastAPI 实例、CORS、路由注册、启动初始化。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from .api import admin, auth, chat, kb, sessions
from .config import settings
from .core.limiter import limiter
from .core.security import hash_password
from .database import Base, SessionLocal, engine
from .models import User
from .services.document_service import recover_interrupted


async def migrate() -> None:
    """轻量迁移：为新加字段补列（create_all 不会改已有表）。"""
    async with engine.begin() as conn:
        # SQLite 不支持 ADD COLUMN IF NOT EXISTS，用异常吞掉"已存在"
        try:
            await conn.exec_driver_sql(
                "ALTER TABLE messages ADD COLUMN cached BOOLEAN NOT NULL DEFAULT 0"
            )
        except Exception:
            pass


async def seed_admin() -> None:
    """首次启动时创建内置管理员账号 admin / 123456。"""
    async with SessionLocal() as db:
        existing = await db.scalar(
            select(User).where(User.username == settings.ADMIN_USERNAME)
        )
        if existing is None:
            db.add(
                User(
                    username=settings.ADMIN_USERNAME,
                    password_hash=hash_password(settings.ADMIN_PASSWORD),
                    nickname="系统管理员",
                    role="admin",
                )
            )
            await db.commit()
            print(f"[init] 已创建管理员账号：{settings.ADMIN_USERNAME}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建表 + 种子管理员 + 恢复上次中断的文档处理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate()
    await seed_admin()
    await recover_interrupted()
    # 确保 Qdrant 向量集合存在（幂等）；冷启动时 Qdrant 可能未就绪，重试最多 60s
    from .services.vector_store import ensure_collection

    for attempt in range(12):
        try:
            await ensure_collection()
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 11:
                raise
            print(f"[init] Qdrant 未就绪，{5 * (attempt + 1)}s 后重试 ({e})")
            await asyncio.sleep(5 * (attempt + 1))
    yield
    # 关闭：释放连接池
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="基于 LangChain 的企业级 RAG 知识库问答系统",
    lifespan=lifespan,
)

# 限流：注册慢速攻击防护（429 响应由 slowapi 统一处理）
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 跨域：允许前端开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册（统一 /api 前缀）
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(sessions.router, prefix=settings.API_PREFIX)
app.include_router(chat.router, prefix=settings.API_PREFIX)
app.include_router(kb.router, prefix=settings.API_PREFIX)
app.include_router(admin.router, prefix=settings.API_PREFIX)


@app.get("/api/health", summary="健康检查")
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
