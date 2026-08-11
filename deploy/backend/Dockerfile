# ==========================================================
# 后端镜像：FastAPI + LangChain RAG + 本地 bge 向量模型
# 构建上下文 = 项目根目录（依赖根目录 .dockerignore 排除大文件）
# 基础镜像走 DaoCloud 镜像（服务器无法直连 Docker Hub）
# 用 Python 3.12：aliyun CPU torch 镜像暂缺 3.13 轮子
# ==========================================================
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---------- CPU 版 PyTorch（官方 CPU index，约 180MB）----------
# 必须先装：sentence-transformers 依赖 torch，若后装会从 PyPI 拉 2GB CUDA 包
# （aliyun pytorch-wheels/cpu 镜像已失效，改用官方 CPU index，实测 14MB/s）
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# ---------- Python 依赖（清华 PyPI 镜像，国内加速）----------
COPY backend/requirements.txt .
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# ---------- 应用代码 ----------
COPY backend/app ./app
COPY scripts/download_model.py ./scripts/download_model.py
COPY backend/entrypoint.sh ./entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000
CMD ["./entrypoint.sh"]
