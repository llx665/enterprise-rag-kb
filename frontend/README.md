# 前端（Vue 3 + Vite + Element Plus）

本项目是「企业级 RAG 知识库问答系统」的前端部分。完整说明（功能、架构、启动方式、部署）见仓库根目录 [README](../README.md)。

- 技术栈：Vue 3（`<script setup>`）· Vite · Element Plus · Pinia · Axios
- 核心页面：登录/注册、AI 对话（SSE 流式 + 工具调用状态 + 引用溯源）、知识库管理（管理员）、数据看板
- 流式解析：`src/api/chat.js` 封装 SSE 事件（`meta` / `delta` / `tool` / `done`），对话页在 `Chat.vue` 中按事件渲染

## 本地运行

```bash
npm install
npm run dev    # http://localhost:5173（后端默认 http://localhost:8000，见 vite.config.js 代理）
```

## 生产构建

```bash
npm run build   # 产物在 dist/，由 deploy 流程拷贝为 deploy/frontend_dist/ 供 Nginx 托管
```
