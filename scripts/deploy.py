"""生产部署脚本：上传代码到阿里云服务器并启动 Docker Compose。

流程：
1. 检查服务器已具备的条件（Docker / 磁盘空间）
2. 上传部署工件到 /opt/rag-kb/（远端布局即 compose 构建上下文）
3. docker compose build（拉取镜像、构建后端镜像，含 CPU torch）
4. docker compose up -d 启动
5. 等待健康检查通过

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/deploy.py
"""
import os
import sys
import time

# 强制 UTF-8 输出（Windows 控制台默认 GBK，无法打印 ✅ 等 emoji）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import paramiko

# 服务器凭据：从 deploy/server_secrets.py（gitignore）或环境变量读取，不硬编码
from _creds import HOST, PORT, USER, PASSWORD

REMOTE_DIR = "/opt/rag-kb"

# 远端目录布局（= compose 构建上下文，见 docker-compose.yml）
# /opt/rag-kb/
#   docker-compose.yml  .env.production  nginx.conf  .dockerignore
#   backend/{Dockerfile, entrypoint.sh, requirements.txt, app/**}
#   scripts/download_model.py
#   frontend_dist/**


def get_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
    # 保活：避免空闲连接被服务端断开
    client.get_transport().set_keepalive(15)
    return client


def put_with_retry(client, sftp, local: str, remote: str, tries: int = 4) -> None:
    """上传单个文件，失败自动重连并重试。"""
    for attempt in range(1, tries + 1):
        try:
            sftp.put(local, remote)
            return
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 上传失败(第{attempt}次): {remote} ({e})")
            if attempt == tries:
                raise
            time.sleep(5 * attempt)
            try:
                sftp.close()
            except Exception:
                pass
            sftp = client.open_sftp()
    raise SystemExit(f"上传失败: {remote}")


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 900) -> None:
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out)
    if err.strip():
        print("[stderr]", err)
    if code != 0:
        raise SystemExit(f"命令失败: {cmd}")


def upload_dir(client, sftp, local: str, remote: str) -> None:
    """递归上传目录（跳过缓存与隐藏目录，逐文件重试）。"""
    for root, dirs, files in os.walk(local):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".venv", "node_modules")]
        rel = os.path.relpath(root, local)
        target = remote if rel == "." else f"{remote}/{rel.replace(os.sep, '/')}"
        try:
            sftp.stat(target)
        except IOError:
            sftp.mkdir(target)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            put_with_retry(client, sftp, os.path.join(root, f), f"{target}/{f}")


def main() -> None:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client = get_client()
    print(f"✅ 已连接 {HOST}")

    # ---------- 1. 预检查 ----------
    run(client, "docker --version && docker compose version && df -h / | tail -1 && free -h | head -2")

    # ---------- 2. 上传 ----------
    run(client, f"mkdir -p {REMOTE_DIR}/backend {REMOTE_DIR}/scripts")
    sftp = client.open_sftp()
    uploads = [
        ("deploy/docker-compose.yml", "docker-compose.yml"),
        ("deploy/.env.production", ".env.production"),
        ("deploy/nginx.conf", "nginx.conf"),
        (".dockerignore", ".dockerignore"),
        ("deploy/backend/Dockerfile", "backend/Dockerfile"),
        ("deploy/backend/entrypoint.sh", "backend/entrypoint.sh"),
        ("backend/requirements.txt", "backend/requirements.txt"),
        ("backend/app", "backend/app"),
        ("scripts/download_model.py", "scripts/download_model.py"),
        ("deploy/frontend_dist", "frontend_dist"),
    ]
    print("\n=== 上传 ===")
    for local, remote in uploads:
        lp = os.path.join(ROOT, local)
        rp = f"{REMOTE_DIR}/{remote}"
        if os.path.isdir(lp):
            upload_dir(client, sftp, lp, rp)
        else:
            put_with_retry(client, sftp, lp, rp)
        print(f"  ✅ {local} -> {remote}")
    sftp.close()

    # ---------- 3. 构建与启动 ----------
    # 服务器仅 1.6G 内存 + 国内镜像，pip 安装可能很慢，放宽到 30 分钟
    run(client, f"cd {REMOTE_DIR} && docker compose build backend", timeout=1800)
    run(client, f"cd {REMOTE_DIR} && docker compose up -d", timeout=300)

    # ---------- 4. 健康检查 ----------
    print("\n=== 等待服务启动（最多 2 分钟）===")
    ok = False
    for i in range(24):
        time.sleep(5)
        transport = client.get_transport().open_session()
        transport.exec_command("curl -s http://localhost:8083/api/health")
        out = transport.makefile().read().decode("utf-8", "replace")
        if out.strip():
            print("✅ 健康检查通过:", out.strip())
            ok = True
            break
    if not ok:
        print("⚠️ 健康检查超时，查看日志: docker compose -f /opt/rag-kb/docker-compose.yml logs")

    client.close()
    if ok:
        print("\n🎉 部署完成，访问 http://47.101.151.35/")
        print("   管理员账号 admin / 123456")


if __name__ == "__main__":
    main()
