"""pytest 全局配置：独立测试库 + 关闭限流/缓存 + 进入 lifespan 的 TestClient。

注意：本文件的 env 设置必须在导入 app 之前执行
（pydantic-settings 的环境变量优先级高于 .env 文件）。
"""
import os
from pathlib import Path

# ---------- 独立测试数据库（不污染开发库 dev.db） ----------
TEST_DB = Path(__file__).resolve().parent / "test_runtime.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
# 关闭限流 / 语义缓存，避免 429 拦截与真实模型调用
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["CACHE_ENABLED"] = "false"
os.environ["DEEPSEEK_API_KEY"] = "test-only"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import vector_store  # noqa: E402


async def _ensure_noop():
    """测试不依赖 Qdrant：把启动时的集合初始化替换为空操作。

    lifespan 内部是 `from .services.vector_store import ensure_collection`，
    在此把模块属性替换即可（函数内导入发生在调用时）。
    """
    return None


vector_store.ensure_collection = _ensure_noop


@pytest.fixture(scope="session")
def client():
    """进入 lifespan 的测试客户端：自动建表 + 种子管理员 admin/123456。

    用 `with` 让 TestClient 运行 lifespan（在应用自己的事件循环里建表），
    避免测试进程循环与 aiosqlite 连接池跨循环的问题。
    """
    with TestClient(app) as c:
        yield c
