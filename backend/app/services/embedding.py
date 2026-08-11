"""文本向量化服务（双模式）。

模式一（默认，推荐）：本地离线模型 bge-small-zh-v1.5
    - 无需任何第三方 API Key，完全自托管
    - 模型下载到 infra/models/bge-small-zh-v1.5（见 scripts/download_model.py）
    - CPU 即可运行，一次加载全局复用

模式二：SiliconFlow 的 BAAI/bge-m3 API（OpenAI 兼容）
    - 需要 SiliconFlow API Key，向量效果更强
    - 通过 EMBEDDING_PROVIDER=siliconflow 切换

两种模式封装为统一的 Embeddings 接口（embed_query / embed_documents / 异步），
上层（检索/入库）无需感知具体实现。

关于 bge 检索指令前缀：bge 系列模型在检索任务中建议给「查询」加指令前缀
「为这个句子生成表示以用于检索相关文章：」，而「文档」不加 —— 这是非对称
检索的关键细节，直接决定召回效果，因此这里用 SentenceTransformer 显式封装，
而不是依赖已弃用的 langchain_community.HuggingFaceBgeEmbeddings。
"""
from functools import lru_cache
from pathlib import Path

from ..config import settings

# bge 检索指令前缀（查询专用，文档不加）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class LocalBgeEmbeddings:
    """本地 bge-small-zh 向量模型封装（兼容 LangChain Embeddings 接口）。"""

    def __init__(self, model_path: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_path, device="cpu")

    # ---- 同步接口 ----
    def embed_query(self, text: str) -> list[float]:
        """查询向量：加 bge 检索指令前缀（非对称检索关键）。"""
        return (
            self._model.encode(
                [QUERY_INSTRUCTION + text],
                normalize_embeddings=True,
            )[0]
            .tolist()
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """文档向量：批量编码，不加指令前缀。"""
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vecs]

    # ---- 异步接口（LangChain 会调用） ----
    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


def get_embeddings():
    """获取全局 Embedding 客户端（单例、线程安全、连接复用）。"""
    if settings.EMBEDDING_PROVIDER == "siliconflow":
        return _get_siliconflow_embeddings()
    return _get_local_embeddings()


@lru_cache
def _get_local_embeddings():
    """本地 bge-small-zh-v1.5：加载本地目录模型。"""
    model_path = Path(settings.LOCAL_MODEL_PATH)
    if not model_path.exists():
        raise RuntimeError(
            f"本地向量模型不存在：{model_path}。请先运行：\n"
            f"  cd backend && .venv/Scripts/python.exe ..\\scripts\\download_model.py"
        )
    return LocalBgeEmbeddings(str(model_path))


@lru_cache
def _get_siliconflow_embeddings():
    """SiliconFlow bge-m3（OpenAI 兼容接口）。"""
    if not settings.EMBEDDING_API_KEY:
        raise RuntimeError(
            "未配置 EMBEDDING_API_KEY。请在 backend/.env 中填写 SiliconFlow 的 Key，"
            "或改用本地模型（EMBEDDING_PROVIDER=local）"
        )

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        check_embedding_ctx_length=False,
    )
