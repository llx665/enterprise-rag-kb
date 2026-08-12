"""MCP Streamable HTTP 冒烟测试：对运行中的 HTTP MCP 服务器走完整协议握手。

前置：先启动 MCP HTTP 服务（另一终端）：
    python backend/run_mcp_server.py --transport http --port 8001

用法：
    backend/.venv/Scripts/python.exe scripts/test_mcp_http.py [base_url]
    默认 base_url = http://127.0.0.1:8001/mcp
"""
import json
import os
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001/mcp"


def main() -> int:
    with httpx.Client(timeout=30) as client:
        # 1. initialize（建立会话）
        r = client.post(
            BASE,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "http-smoke", "version": "1.0"},
                },
            },
        )
        r.raise_for_status()
        sid = r.headers.get("mcp-session-id")
        assert sid, "缺少 mcp-session-id 响应头"
        print("initialize OK，session-id:", sid[:12] + "…")

        # 2. notifications/initialized
        client.post(
            BASE,
            headers={"Content-Type": "application/json", "mcp-session-id": sid},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        # 3. tools/list
        r = client.post(
            BASE,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": sid},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        # SSE 响应里 data 行是 JSON
        data_line = next(l for l in r.text.splitlines() if l.startswith("data: "))
        result = json.loads(data_line[6:])["result"]
        names = sorted(t["name"] for t in result["tools"])
        print("工具列表:", names)
        assert names == ["kb_agent", "kb_ask", "kb_documents", "kb_search", "kb_stats"]

        # 4. tools/call kb_stats
        r = client.post(
            BASE,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": sid},
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kb_stats", "arguments": {}}},
        )
        data_line = next(l for l in r.text.splitlines() if l.startswith("data: "))
        call_result = json.loads(data_line[6:])["result"]
        text = call_result["content"][0]["text"]
        print("kb_stats 返回:", text[:200])

    print("\nMCP HTTP SMOKE PASS ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
