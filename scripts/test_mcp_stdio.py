"""MCP stdio 冒烟测试（裸协议）：用 JSON-RPC over stdio 直连本地 MCP 服务器。

不依赖 mcp SDK 客户端（其 2.0 API 变动较大），直接按 MCP 标准协议发送
newline-delimited JSON-RPC，行为最接近真实客户端（Claude Code / Claude Desktop）。
会真实调用工具：kb_stats（读 DB）、kb_search（向量化 + 检索 Qdrant）。

前置：先启动 Qdrant（infra/qdrant/qdrant.exe），否则 kb_search 返回空结果。

用法：
    backend/.venv/Scripts/python.exe scripts/test_mcp_stdio.py
"""
import json
import os
import subprocess
import sys

_BACKEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"
)
_VENV_PY = os.path.join(_BACKEND, ".venv", "Scripts", "python.exe")
# 默认用 venv python；设 MCP_TEST_PYTHON=python 可用 PATH 里的 python 走一遍引导逻辑
_PY = os.environ.get("MCP_TEST_PYTHON", _VENV_PY)
_ENTRY = os.path.join(_BACKEND, "run_mcp_server.py")


def _send(proc, obj):
    proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def _recv(proc):
    """读取一条 JSON-RPC 响应；跳过服务器 stdout 上的非 JSON 日志行。"""
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"服务器提前退出：{proc.stderr.read()}")
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            print(f"[跳过日志] {line.strip()}")


def _rpc(proc, mid, method, params):
    _send(proc, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
    msg = _recv(proc)
    assert msg.get("id") == mid, f"id 不匹配：{msg}"
    assert "error" not in msg, f"RPC 错误：{msg.get('error')}"
    return msg["result"]


def main() -> int:
    proc = subprocess.Popen(
        [_PY, _ENTRY],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    try:
        # 1. initialize 握手
        res = _rpc(proc, 1, "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1.0"},
        })
        print("serverInfo:", res.get("serverInfo"))
        print("instructions 前 80 字:", (res.get("instructions") or "")[:80].replace("\n", " "))

        # 2. 通知初始化完成
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 3. tools/list
        tools = _rpc(proc, 2, "tools/list", {})
        names = sorted(t["name"] for t in tools["tools"])
        print("工具列表:", names)
        assert names == ["kb_agent", "kb_ask", "kb_documents", "kb_search", "kb_stats"]

        # 4. tools/call kb_stats（读 DB）
        result = _rpc(proc, 3, "tools/call", {"name": "kb_stats", "arguments": {}})
        text = result["content"][0]["text"]
        print("kb_stats 返回:", text[:200])
        assert '"total_documents"' in text

        # 5. tools/call kb_search（向量化 + 混合检索）
        result = _rpc(proc, 4, "tools/call", {
            "name": "kb_search",
            "arguments": {"query": "手机充电器快充", "top_k": 3},
        })
        text = result["content"][0]["text"]
        print("kb_search 返回:", text[:300])
        assert '"count"' in text

        # 6. tools/call kb_ask（RAG 问答，走真实 LLM；失败时工具会返回降级提示）
        result = _rpc(proc, 5, "tools/call", {
            "name": "kb_ask",
            "arguments": {"question": "充电宝支持多少瓦快充？"},
        })
        text = result["content"][0]["text"]
        print("kb_ask 返回:", text[:400])
        assert ('"answer"' in text) or ("暂不可用" in text)

        # 7. tools/call kb_documents（读 DB）
        result = _rpc(proc, 6, "tools/call", {"name": "kb_documents", "arguments": {}})
        text = result["content"][0]["text"]
        print("kb_documents 返回:", text[:160])
        assert '"documents"' in text

        # 8. tools/call kb_agent（Agent 链路，走真实 LLM；失败时返回降级提示）
        result = _rpc(proc, 7, "tools/call", {
            "name": "kb_agent",
            "arguments": {"question": "今天是几月几号"},
        })
        text = result["content"][0]["text"]
        print("kb_agent 返回:", text[:300])
        assert text.strip() and ("暂不可用" not in text or "今天" in text)

        print("\nMCP STDIO RAW PROTOCOL SMOKE PASS ✔")
        return 0
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(main())
