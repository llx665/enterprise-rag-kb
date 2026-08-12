"""云端闭环验证：登录 -> RAG 商品问答 + Agent 工具问答（SSE 流式）。"""
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx

BASE = "http://47.101.151.35/api"


def sse_request(client: httpx.Client, headers: dict, question: str) -> None:
    """发送 SSE 流式请求并拼装事件。"""
    print(f"\nQ: {question}")
    citations = []
    answer_parts = []
    tools = []
    done = None
    with client.stream(
        "POST",
        f"{BASE}/chat",
        headers=headers,
        json={"question": question},
        timeout=120,
    ) as r:
        print(f"  HTTP {r.status_code}")
        event = None
        for line in r.iter_lines():
            line = line.strip()
            if not line:
                event = None
                continue
            if line.startswith("event: "):
                event = line[len("event: ") :]
                continue
            if line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if event == "meta":
                    citations = data.get("citations", [])
                elif event == "tool":
                    tools.append(data)
                elif event == "delta":
                    answer_parts.append(data.get("content", ""))
                elif event == "done":
                    done = data
                elif event == "error":
                    print("  ❌ 错误事件:", data.get("detail"))
                    return
    answer = "".join(answer_parts)
    print(f"  工具调用: {tools if tools else '无'}")
    print(f"  引用来源: {[c.get('doc_name') for c in citations]}")
    print(f"  答案前 200 字: {answer[:200]}")
    if done:
        print(f"  完成: latency={done.get('latency_ms')}ms cached={done.get('cached')}")
    ok = bool(answer.strip()) and (not tools or tools)
    print(f"  {'✅ 通过' if ok else '❌ 失败'}")


def main() -> None:
    with httpx.Client(timeout=60) as client:
        r = client.post(
            f"{BASE}/auth/login", json={"username": "admin", "password": "123456"}
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ 登录成功（admin）")

        # 1. RAG 商品问题：应走混合检索并带引用
        sse_request(client, headers, "星辰 X1 Pro 支持多少瓦快充？")
        # 2. Agent 工具问题：应触发计算器工具
        sse_request(client, headers, "1200 块打 85 折再满 300 减 50，最后多少钱？")
        # 3. Agent 日历问题
        sse_request(client, headers, "今天是几月几号，农历几号？")


if __name__ == "__main__":
    main()
