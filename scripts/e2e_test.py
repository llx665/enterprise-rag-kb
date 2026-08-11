"""端到端测试脚本：登录 -> 知识库检索 -> RAG 问答 -> 语义缓存。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/e2e_test.py
"""
import json
import sys
import time

# 强制 UTF-8 输出（Windows 控制台默认 GBK，无法打印 ✅ 等 emoji）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import httpx

BASE = "http://localhost:8000/api"


def login(client: httpx.Client, username: str, password: str) -> str:
    r = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    with httpx.Client(timeout=60) as client:
        # ---------- 1. 登录 ----------
        token = login(client, "admin", "123456")
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ 管理员登录成功")

        # ---------- 2. 知识库统计 ----------
        stats = client.get(f"{BASE}/kb/stats", headers=headers).json()
        print(f"✅ 知识库统计: 文档={stats['ready_documents']} 分块={stats['total_chunks']} 向量点={stats['vector_points']}")

        # ---------- 3. 混合检索测试 ----------
        print("\n--- 混合检索：语义+关键词 ---")
        r = client.post(
            f"{BASE}/kb/search",
            headers=headers,
            json={"query": "苹果手机保修多久？退货运费谁承担？", "top_k": 3},
        )
        for h in r.json():
            print(f"  score={h['score']} 块{h['chunk_index']}: {h['content'][:38].replace(chr(10),' ')}")

        # ---------- 4. RAG 问答（SSE 流式） ----------
        print("\n--- RAG 问答（DeepSeek 流式）---")
        q = "苹果手机支持退换货吗？政策是什么？"
        with client.stream("POST", f"{BASE}/chat", headers=headers, json={"question": q}) as resp:
            answer, citations, done = "", [], None
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if "content" in payload:
                    answer += payload["content"]
                elif "citations" in payload:
                    citations = payload["citations"]
                elif "message_id" in payload:
                    done = payload
            print(f"  回答: {answer[:120]}...")
            print(f"  引用块数: {len(citations)}, 延迟: {done['latency_ms']}ms, 命中缓存: {done.get('cached')}")

        # ---------- 5. 语义缓存：同义问题第二次应命中 ----------
        print("\n--- 语义缓存：重复问同义问题 ---")
        q2 = "苹果手机能不能退货？"
        with client.stream("POST", f"{BASE}/chat", headers=headers, json={"question": q2}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "cached" in payload:
                        print(f"  第一次提问 命中缓存: {payload['cached']}")
                    elif "latency_ms" in payload and "message_id" in payload:
                        print(f"  done: latency={payload['latency_ms']}ms cached={payload['cached']}")
        with client.stream("POST", f"{BASE}/chat", headers=headers, json={"question": q2}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "latency_ms" in payload and "message_id" in payload:
                        print(f"  第二次提问 命中缓存: {payload['cached']} latency={payload['latency_ms']}ms")

        # ---------- 6. 会话历史 ----------
        sessions = client.get(f"{BASE}/sessions", headers=headers).json()
        print(f"\n✅ 会话列表: {len(sessions)} 个会话")


if __name__ == "__main__":
    main()
