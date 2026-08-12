"""查看服务器部署进度：docker 容器 / 镜像 / compose 状态 / 构建日志尾部。"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import paramiko

from _creds import HOST, PORT, USER, PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
client.get_transport().set_keepalive(15)

cmds = [
    "echo '=== 容器 ===' && docker ps -a --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null",
    "echo '=== 镜像 ===' && docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' 2>/dev/null | head -8",
    "echo '=== 上传目录 ===' && ls /opt/rag-kb/ 2>/dev/null && du -sh /opt/rag-kb/backend/app 2>/dev/null",
    "echo '=== 构建进程 ===' && docker system df 2>/dev/null | head -3",
    "echo '=== 内存 ===' && free -h | head -2",
]
for c in cmds:
    stdin, stdout, stderr = client.exec_command(c, timeout=60)
    out = stdout.read().decode("utf-8", "replace")
    if out.strip():
        print(out)

# 若 buildkit 正在构建，能看到 buildx/buildkit 容器或镜像层在增长
stdin, stdout, stderr = client.exec_command(
    "docker images -q | wc -l && docker ps -q | wc -l", timeout=30
)
n_images, n_containers = stdout.read().decode().split()
print(f"[image 数量={n_images}, 运行容器={n_containers}]")
client.close()
