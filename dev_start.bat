@echo off
chcp 65001 >nul
cd /d %~dp0

echo ============================================
echo   企业级 RAG 知识库问答系统 - 一键启动
echo ============================================
echo.

echo [1/3] 启动 Qdrant 向量数据库...
start "Qdrant" cmd /k "cd /d %~dp0infra\qdrant && qdrant.exe"

timeout /t 4 /nobreak >nul

echo [2/3] 启动后端 API (FastAPI)...
start "Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [3/3] 启动前端 (Vue3)...
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo 全部启动完成！
echo   - 前端页面:  http://localhost:5173
echo   - 后端文档:  http://localhost:8000/docs
echo   - Qdrant:    http://localhost:6333
echo   - 管理员账号: admin / 123456
echo.
echo 关闭此窗口不影响已启动的服务。
pause
