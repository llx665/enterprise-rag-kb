"""应用配置：集中管理所有环境变量。

使用 pydantic-settings 从 .env / 环境变量读取配置，
所有模块统一通过 `get_settings()` 获取单例配置对象。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用 ----------
    APP_NAME: str = "企业级 RAG 知识库问答系统"
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # ---------- 安全 ----------
    SECRET_KEY: str = "change-me-in-production"
    TOKEN_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60          # 访问令牌有效期（分钟）
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7             # 刷新令牌有效期（天）

    # ---------- 数据库 ----------
    DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"

    # ---------- 管理员种子账号 ----------
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "123456"

    # ---------- DeepSeek LLM ----------
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.3

    # ---------- Embedding 向量化 ----------
    # 模式：local（本地 bge-small-zh，无需 Key，默认） / siliconflow（bge-m3 API）
    EMBEDDING_PROVIDER: str = "local"
    EMBEDDING_DIM: int = 512  # bge-small-zh-v1.5 向量维度（siliconflow bge-m3 为 1024）
    # 本地模型路径（bge-small-zh-v1.5）
    LOCAL_MODEL_PATH: str = "../infra/models/bge-small-zh-v1.5"
    # SiliconFlow bge-m3（可选模式，需 Key）
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"

    # ---------- 向量库 Qdrant ----------
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "kb_documents"

    # ---------- Redis（可选，未配置则降级为内存实现）----------
    REDIS_URL: str = ""

    # ---------- 语义缓存（相似问题命中缓存，避免重复调用 LLM）----------
    CACHE_ENABLED: bool = True
    CACHE_MAX_ENTRIES: int = 200          # 缓存条目上限
    CACHE_SIMILARITY_THRESHOLD: float = 0.93  # 问题向量余弦相似度阈值，高于则命中

    # ---------- 混合检索 / 重排序 ----------
    # 稀疏检索（jieba+BM25）参与 RRF 融合的权重体系；RRF_K 为平滑常数
    RRF_K: int = 60
    # 重排序模型（bge-reranker），可选；默认关闭，配置后自动启用
    RERANK_ENABLED: bool = False
    RERANK_MODEL_PATH: str = "../infra/models/bge-reranker-base"
    RERANK_TOP_N: int = 6                 # 重排序后保留的最终候选数

    # ---------- 接口限流 ----------
    RATE_LIMIT_ENABLED: bool = True

    # ---------- CORS ----------
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # ---------- 知识库：上传与分块 ----------
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    CHUNK_SIZE: int = 800                 # 分块大小（字符）
    CHUNK_OVERLAP: int = 120              # 分块重叠（保证上下文连续）
    RETRIEVE_TOP_K: int = 8               # RAG 检索返回的候选块数量


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
