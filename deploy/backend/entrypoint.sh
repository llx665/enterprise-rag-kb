#!/bin/bash
# 后端容器启动脚本：首次启动下载本地向量模型，然后启动 uvicorn
set -e

MODEL_DIR="${LOCAL_MODEL_PATH:-/models/bge-small-zh-v1.5}"

# 本地向量模型不存在则自动下载（ModelScope，国内直连）
if [ ! -f "$MODEL_DIR/model.safetensors" ]; then
  echo "[init] 下载本地向量模型 bge-small-zh-v1.5 ..."
  mkdir -p "$MODEL_DIR"
  python /app/scripts/download_model.py --target "$MODEL_DIR"
fi

echo "[init] 启动后端服务 ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
