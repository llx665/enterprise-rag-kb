"""初始化演示知识库：清空旧文档，上传 demo_data/ 下全部演示文档。

文档会经过 分块 -> 向量化 -> 写入 Qdrant 的完整流水线。
文件名走 UTF-8 上传，避免 Windows 控制台导致的 GBK 乱码。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/seed_kb.py
"""
import glob
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import httpx

BASE = "http://localhost:8000/api"
DEMO_DIR = "../demo_data"


def login(client: httpx.Client) -> dict:
    r = client.post(f"{BASE}/auth/login", json={"username": "admin", "password": "123456"})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def delete_all(client: httpx.Client, headers: dict) -> None:
    docs = client.get(f"{BASE}/kb/documents", headers=headers, params={"page_size": 100}).json()
    for d in docs["items"]:
        client.delete(f"{BASE}/kb/documents/{d['id']}", headers=headers)
        print(f"  已删除旧文档: id={d['id']} {d['filename']}")
    if not docs["items"]:
        print("  无旧文档")


def main() -> None:
    with httpx.Client(timeout=120) as client:
        headers = login(client)
        print("✅ 管理员登录成功")

        print("\n=== 清理旧知识库 ===")
        delete_all(client, headers)

        print("\n=== 上传演示文档 ===")
        files = sorted(glob.glob(f"{DEMO_DIR}/*.md"))
        for fp in files:
            # Windows 路径是反斜杠，用 basename 取纯文件名
            name = os.path.basename(fp)
            with open(fp, "rb") as f:
                r = client.post(
                    f"{BASE}/kb/documents",
                    headers=headers,
                    files={"file": (name, f, "text/markdown")},
                )
            if r.status_code == 201:
                print(f"  ✅ {name} (id={r.json()['id']}) 已上传，后台处理中")
            else:
                print(f"  ❌ {name} 上传失败: {r.status_code} {r.text[:120]}")

        # ---------- 轮询直到全部处理完成 ----------
        print("\n=== 等待后台处理（分块 + 向量化）===")
        for _ in range(60):
            time.sleep(2)
            docs = client.get(f"{BASE}/kb/documents", headers=headers, params={"page_size": 100}).json()
            pending = [d for d in docs["items"] if d["status"] != "ready"]
            failed = [d for d in docs["items"] if d["status"] in ("failed", "error")]
            if not pending:
                break
            print(f"  处理中... 剩余 {len(pending)} 个文档", end="\r")
        print()

        stats = client.get(f"{BASE}/kb/stats", headers=headers).json()
        print("\n=== 知识库最终状态 ===")
        print(
            f"文档 {stats['ready_documents']} 个 / 分块 {stats['total_chunks']} 块 / "
            f"向量点 {stats['vector_points']} 个"
        )
        docs = client.get(f"{BASE}/kb/documents", headers=headers, params={"page_size": 100}).json()
        for d in docs["items"]:
            print(f"  [{d['status']}] {d['filename']}  (块数: {d.get('chunk_count', '?')})")


if __name__ == "__main__":
    main()
