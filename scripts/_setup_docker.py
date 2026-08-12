"""一次性服务器初始化：安装 docker + compose v2 + 创建 2G swapfile。

整机重装后的前提准备。凭据从 deploy/server_secrets.py（gitignore）读取。
"""
import time

import paramiko

from _creds import HOST, PORT, USER, PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, PORT, USER, PASSWORD, timeout=60)
client.get_transport().set_keepalive(15)

cmd = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
echo "[1/4] apt-get update ..."
apt-get update -qq
echo "[2/4] 安装 docker.io + docker-compose-v2 ..."
apt-get install -y -qq docker.io docker-compose-v2
systemctl enable --now docker
echo "[3/4] 创建 2G swapfile（防向量化峰值内存打爆）..."
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo "[4/4] 版本确认："
docker --version
docker compose version
free -h
"""

try:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=600, get_pty=True)
    for line in iter(stdout.readline, ""):
        print(line, end="")
    code = stdout.channel.recv_exit_status()
    print(f"[exit={code}]")
finally:
    client.close()
