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

BASE = os.environ.get("SEED_BASE_URL", "http://localhost:8000/api")
DEMO_DIR = os.environ.get("DEMO_DIR", "../demo_data")


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


def mime_for(name: str) -> str:
    """按扩展名映射 MIME 类型（代码文件走 octet-stream，其余用常见类型）。"""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "md": "text/markdown",
        "txt": "text/plain",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


def main() -> None:
    with httpx.Client(timeout=120) as client:
        headers = login(client)
        print("✅ 管理员登录成功")

        print("\n=== 清理旧知识库 ===")
        delete_all(client, headers)

        print("\n=== 上传演示文档（逐个上传，等 ready 再传下一个）===")
        files = sorted(glob.glob(f"{DEMO_DIR}/*"))
        files = [f for f in files if os.path.isfile(f)]
        for fp in files:
            # Windows 路径是反斜杠，用 basename 取纯文件名
            name = os.path.basename(fp)
            with open(fp, "rb") as f:
                r = client.post(
                    f"{BASE}/kb/documents",
                    headers=headers,
                    files={"file": (name, f, mime_for(name))},
                )
            if r.status_code != 201:
                print(f"  ❌ {name} 上传失败: {r.status_code} {r.text[:120]}")
                continue
            doc_id = r.json()["id"]
            print(f"  {name} (id={doc_id}) 已上传，等待处理…")

            # 轮询等待当前文档处理完成（单线程向量化，内存友好）
            ok = False
            for _ in range(120):
                time.sleep(3)
                d = client.get(f"{BASE}/kb/documents/{doc_id}", headers=headers).json()
                if d["status"] == "ready":
                    ok = True
                    break
                if d["status"] in ("failed", "error"):
                    print(f"  ❌ {name} 处理失败: {d.get('error_message', '')[:120]}")
                    break
            if ok:
                print(f"  ✅ {name} ready（块数: {d.get('chunk_count', '?')}）")

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
