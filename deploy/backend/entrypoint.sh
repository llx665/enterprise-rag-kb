#!/bin/bash
# 后端容器启动脚本：首次启动下载本地向量模型，然后启动 uvicorn
set -e

MODEL_DIR="${LOCAL_MODEL_PATH:-/models/bge-small-zh-v1.5}"

# 应用层使用 ONNX 推理，需要 model.onnx + model.onnx.data + tokenizer.json。
# 基础权重可由 download_model.py 下载；ONNX 由开发机 scripts/export_onnx.py 生成，
# 随部署上传（/opt/rag-kb/models/...）。缺 ONNX 时给出清晰指引。
if [ ! -f "$MODEL_DIR/model.onnx" ]; then
  echo "[init] 缺少 model.onnx，先拉取基础权重 ..."
  mkdir -p "$MODEL_DIR"
  python /app/scripts/download_model.py --target "$MODEL_DIR"
  if [ ! -f "$MODEL_DIR/model.onnx" ]; then
    echo "[init] 警告：model.onnx 仍缺失。请在开发机运行 scripts/export_onnx.py"
    echo "         并将 model.onnx / model.onnx.data 上传到 $MODEL_DIR"
  fi
fi

echo "[init] 启动后端服务 ..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
