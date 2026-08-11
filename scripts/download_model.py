"""下载本地向量模型 bge-small-zh-v1.5（中文检索增强模型）。

来源：ModelScope（国内直连稳定），默认下载到 infra/models/bge-small-zh-v1.5。
该模型约 100MB，CPU 即可运行，无需任何第三方 API Key。

用法：
    cd backend && .venv/Scripts/python.exe ..\scripts\download_model.py [--target 目录]
"""
import argparse
import os
from pathlib import Path


def main() -> None:
    from modelscope import snapshot_download

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
    snapshot_download(
        "AI-ModelScope/bge-small-zh-v1.5",
        local_dir=str(model_dir),
    )
    print("下载完成")


if __name__ == "__main__":
    main()
