"""MCP（Model Context Protocol）集成包。

把本系统的 RAG 知识库能力暴露为 MCP 工具，
供任意 MCP 客户端（Claude Code / Claude Desktop / Cursor 等）直连调用。

入口：`backend/run_mcp_server.py`
- stdio：本机直连（Claude Code .mcp.json / Claude Desktop 配置）
- Streamable HTTP：`python run_mcp_server.py --transport http`（远程访问）
"""
