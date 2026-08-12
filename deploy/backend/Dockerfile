# ==========================================================
# 后端镜像：FastAPI + LangChain RAG + 本地 bge 向量模型
# 构建上下文 = 项目根目录（依赖根目录 .dockerignore 排除大文件）
# 基础镜像走 DaoCloud 镜像（服务器无法直连 Docker Hub）
# 向量模型为 ONNX Runtime 推理，无需 torch
# ==========================================================
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------- Python 依赖（清华 PyPI 镜像，国内加速）----------
# 注：向量模型用 ONNX Runtime 推理（embedding.py），不再安装 torch /
# sentence-transformers —— 1.6G 小机装不下 torch，ONNX 导入仅 ~80MB。
COPY backend/requirements.txt .
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# ---------- 应用代码 ----------
COPY backend/app ./app
COPY scripts/download_model.py ./scripts/download_model.py
COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000
CMD ["./entrypoint.sh"]
