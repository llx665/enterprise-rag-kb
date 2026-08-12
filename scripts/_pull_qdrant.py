"""拉取 qdrant 镜像（daocloud 国内镜像源，放长超时）。"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import paramiko

from _creds import HOST, PORT, USER, PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
client.get_transport().set_keepalive(15)

cmd = "docker pull docker.m.daocloud.io/qdrant/qdrant:v1.19.0"
print(f">>> {cmd}")
stdin, stdout, stderr = client.exec_command(cmd, timeout=590, get_pty=True)
# get_pty: 实时读取 pull 进度
for line in iter(stdout.readline, ""):
    print(line, end="")
code = stdout.channel.recv_exit_status()
print(f"[exit={code}]")
client.close()
