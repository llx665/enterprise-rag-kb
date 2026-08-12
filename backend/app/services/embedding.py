"""文本向量化服务（双模式）。

模式一（默认，推荐）：本地离线模型 bge-small-zh-v1.5（ONNX Runtime 推理）
    - 无需任何第三方 API Key，完全自托管
    - 模型权重导出为 ONNX（scripts/export_onnx.py），CPU 推理
    - 选择 ONNX 的原因：torch CPU 导入就要 ~500MB，1.6G 小机必换页打爆；
      ONNX Runtime 导入仅 ~80MB，本地向量化内存占用 ~200MB，小机可跑
    - 模型目录见 settings.LOCAL_MODEL_PATH，需要 model.onnx + model.onnx.data + tokenizer.json
    - CLS 池化 + L2 归一化在 _embed 中复刻，与 sentence-transformers 输出一致（cos=1.0）

模式二：SiliconFlow 的 BAAI/bge-m3 API（OpenAI 兼容）
    - 需要 SiliconFlow API Key，向量效果更强
    - 通过 EMBEDDING_PROVIDER=siliconflow 切换

两种模式封装为统一的 Embeddings 接口（embed_query / embed_documents / 异步），
上层（检索/入库）无需感知具体实现。

关于 bge 检索指令前缀：bge 系列模型在检索任务中建议给「查询」加指令前缀
「为这个句子生成表示以用于检索相关文章：」，而「文档」不加 —— 这是非对称
检索的关键细节，直接决定召回效果。
"""
import asyncio
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import settings

# bge 检索指令前缀（查询专用，文档不加）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
_MAX_LEN = 512


class LocalBgeEmbeddings:
    """本地 bge-small-zh ONNX 向量模型封装（兼容 LangChain Embeddings 接口）。"""

    def __init__(self, model_path: str) -> None:
        from onnxruntime import InferenceSession, SessionOptions
        from tokenizers import Tokenizer

        self._path = Path(model_path)

        # 小机显存/内存紧张：推理强制单线程，降低峰值内存与 CPU 争抢
        opts = SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        onnx_path = self._path / "model.onnx"
        if not onnx_path.exists():
            raise RuntimeError(
                f"本地向量模型 ONNX 不存在：{onnx_path}。请先在开发机运行：\n"
                f"  cd backend && .venv/Scripts/python.exe ..\\scripts\\export_onnx.py\n"
                f"并将 model.onnx / model.onnx.data 上传到服务器模型目录"
            )
        self._session = InferenceSession(
            str(onnx_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )

        self._tokenizer = Tokenizer.from_file(str(self._path / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=_MAX_LEN)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    # ---- 编码核心：tokenize -> ONNX 前向 -> CLS 池化 -> L2 归一化 ----
    def _embed(self, texts: list[str]) -> list[list[float]]:
        encodings = self._tokenizer.encode_batch(texts)
        batch = len(encodings)
        seq = max((len(e.ids) for e in encodings), default=1)

        input_ids = np.zeros((batch, seq), dtype=np.int64)
        attention_mask = np.zeros((batch, seq), dtype=np.int64)
        token_type_ids = np.zeros((batch, seq), dtype=np.int64)
        for i, e in enumerate(encodings):
            n = len(e.ids)
            input_ids[i, :n] = e.ids
            attention_mask[i, :n] = e.attention_mask
            token_type_ids[i, :n] = e.type_ids

        last_hidden = self._session.run(
            ["last_hidden_state"],
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )[0]  # [batch, seq, hidden]

        # CLS 池化（与 1_Pooling/config.json 的 pooling_mode_cls_token 一致）
        cls = last_hidden[:, 0, :]
        # L2 归一化（与 2_Normalize 模块一致）
        normed = cls / np.clip(np.linalg.norm(cls, axis=1, keepdims=True), 1e-9, None)
        return [v.tolist() for v in normed]

    # ---- 同步接口 ----
    def embed_query(self, text: str) -> list[float]:
        """查询向量：加 bge 检索指令前缀（非对称检索关键）。"""
        return self._embed([QUERY_INSTRUCTION + text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """文档向量：批量编码，不加指令前缀。"""
        return self._embed(texts)

    # ---- 异步接口（LangChain 会调用；CPU 密集，切线程池避免阻塞事件循环）----
    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)


def get_embeddings():
    """获取全局 Embedding 客户端（单例、线程安全、连接复用）。"""
    if settings.EMBEDDING_PROVIDER == "siliconflow":
        return _get_siliconflow_embeddings()
    return _get_local_embeddings()


@lru_cache
def _get_local_embeddings():
    """本地 bge-small-zh-v1.5（ONNX）：懒加载，全局复用。"""
    return LocalBgeEmbeddings(settings.LOCAL_MODEL_PATH)


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
