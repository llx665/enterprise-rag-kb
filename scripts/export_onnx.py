"""将 bge-small-zh-v1.5 从 torch 导出为 ONNX（在开发机上运行一次）。

为什么需要 ONNX：
    阿里云部署机仅 1.6G 内存，torch CPU 导入就要 ~500MB，加上模型必然换页打爆。
    ONNX Runtime CPU 导入仅 ~80MB，总占用从 ~700MB 降到 ~200MB，小机才能跑本地向量模型。

导出结果：
    infra/models/bge-small-zh-v1.5/model.onnx
    （CLS 池化 + L2 归一化在应用层 embedding.py 中复刻，与 sentence-transformers 输出一致）

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/export_onnx.py
"""
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "infra" / "models" / "bge-small-zh-v1.5"
ONNX_PATH = MODEL_DIR / "model.onnx"
MAX_LEN = 512


def main() -> None:
    print(f"加载模型: {MODEL_DIR}")
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    model = AutoModel.from_pretrained(str(MODEL_DIR))
    model.eval()

    dummy = tokenizer(
        ["测试句子", "为这个句子生成表示以用于检索相关文章：样例"],
        padding="max_length",
        truncation=True,
        max_length=MAX_LEN,
        return_tensors="pt",
    )
    with torch.no_grad():
        outputs = model(
            dummy["input_ids"],
            attention_mask=dummy["attention_mask"],
            token_type_ids=dummy["token_type_ids"],
        )
    print(f"验证前向: last_hidden_state {tuple(outputs.last_hidden_state.shape)}")

    torch.onnx.export(
        model,
        (dummy["input_ids"], dummy["attention_mask"], dummy["token_type_ids"]),
        str(ONNX_PATH),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "last_hidden_state": {0: "batch", 1: "seq"},
        },
        opset_version=14,
    )
    print(f"导出成功: {ONNX_PATH} ({ONNX_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
