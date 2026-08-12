"""下载本地向量模型 bge-small-zh-v1.5（中文检索增强模型）。

来源：ModelScope（国内直连稳定），默认下载到 infra/models/bge-small-zh-v1.5。
该模型约 100MB，CPU 即可运行，无需任何第三方 API Key。

若机器未安装 modelscope SDK，自动降级为 hf-mirror.com 直接 HTTP 下载
（国内可用，纯标准库实现，无额外依赖）—— 避免容器启动时因缺包崩溃。

用法：
    cd backend && .venv/Scripts/python.exe ..\scripts\download_model.py [--target 目录]
"""
import argparse
import urllib.request
from pathlib import Path

MODEL_ID = "AI-ModelScope/bge-small-zh-v1.5"
HF_MIRROR_ID = "BAAI/bge-small-zh-v1.5"

# bge-small-zh-v1.5 的完整文件清单（与本地 infra/models 一致）
FILES = [
    "config.json",
    "config_sentence_transformers.json",
    "configuration.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
]


def _download(url: str, dest: Path) -> None:
    print(f"  下载 {dest.relative_to(dest.parents[1]) if len(dest.parts) > 1 else dest.name} <- {url}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        default=None,
        help="下载目标目录（默认 infra/models/bge-small-zh-v1.5）",
    )
    args = parser.parse_args()

    if args.target:
        model_dir = Path(args.target)
    else:
        model_dir = Path(__file__).resolve().parents[1] / "infra" / "models" / "bge-small-zh-v1.5"
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"下载模型到: {model_dir}")

    # 优先 ModelScope SDK；未安装则降级直接下载
    try:
        from modelscope import snapshot_download

        print("使用 ModelScope SDK 下载 …")
        snapshot_download(MODEL_ID, local_dir=str(model_dir))
        print("下载完成")
        return
    except ImportError:
        print("modelscope SDK 未安装，改用 hf-mirror.com 直接下载")

    base = f"https://hf-mirror.com/{HF_MIRROR_ID}/resolve/main"
    for f in FILES:
        dest = model_dir / f
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  跳过已存在: {f}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        _download(f"{base}/{f}", dest)
    print("下载完成")


if __name__ == "__main__":
    main()
