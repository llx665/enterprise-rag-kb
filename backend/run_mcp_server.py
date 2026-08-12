"""MCP 服务器入口：把 RAG 知识库暴露为 MCP 工具。

用法（任意目录均可运行，脚本会自行切到 backend 目录）：
    python run_mcp_server.py                       # stdio 运输（Claude Code / Desktop 本地直连）
    python run_mcp_server.py --transport http      # Streamable HTTP，默认 127.0.0.1:8001
    python run_mcp_server.py --transport http --host 0.0.0.0 --port 8001

自动引导：若当前解释器不是项目 venv（如系统 PATH 里的 python 未装依赖），
脚本会用 backend/.venv/Scripts/python.exe 重新拉起自己，保证 MCP SDK 可用。
"""
import os
import sys

_SCRIPT = os.path.abspath(__file__)
_BACKEND_DIR = os.path.dirname(_SCRIPT)

# 固定工作目录为 backend：保证 backend/.env、../infra/models 等相对路径正确
os.chdir(_BACKEND_DIR)
sys.path.insert(0, _BACKEND_DIR)

# 引导：非 venv 解释器 -> 用 venv python 重启（避免缺依赖）。
# 注意必须用绝对脚本路径，否则 os.chdir 后 argv[0] 相对路径会解析失败。
_VENV_PY = os.path.join(_BACKEND_DIR, ".venv", "Scripts", "python.exe")
if ".venv" not in sys.executable.lower() and os.path.exists(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY, _SCRIPT] + sys.argv[1:])

import argparse  # noqa: E402
import asyncio  # noqa: E402

from app.config import settings  # noqa: E402
from app.mcp.server import mcp  # noqa: E402


class _BearerGuard:
    """HTTP 模式可选鉴权：要求 Authorization: Bearer <MCP_HTTP_TOKEN>。"""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            if headers.get(b"authorization") != self.expected:
                from starlette.responses import PlainTextResponse

                resp = PlainTextResponse(
                    "未授权：需要正确的 Authorization: Bearer <MCP_HTTP_TOKEN>",
                    status_code=401,
                )
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _run_stdio() -> None:
    asyncio.run(mcp.run_stdio_async())


def _run_http(host: str, port: int) -> None:
    import uvicorn

    app = mcp.streamable_http_app(streamable_http_path="/mcp", host=host)
    if settings.MCP_HTTP_TOKEN:
        app = _BearerGuard(app, settings.MCP_HTTP_TOKEN)
    print(f"[MCP] Streamable HTTP 服务已启动：http://{host}:{port}/mcp")
    if settings.MCP_HTTP_TOKEN:
        print("[MCP] 已启用 Bearer Token 鉴权（MCP_HTTP_TOKEN）")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 知识库 MCP 服务器")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="运输方式（默认 stdio，本机直连）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址（默认本机）")
    parser.add_argument("--port", type=int, default=8001, help="HTTP 监听端口（默认 8001）")
    args = parser.parse_args()

    if args.transport == "http":
        _run_http(args.host, args.port)
    else:
        _run_stdio()


if __name__ == "__main__":
    main()
