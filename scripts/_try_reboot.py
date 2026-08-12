"""一次性恢复助手：用更长超时尝试 SSH 直连并重启服务器（内存死亡螺旋恢复）。

只在 ssh_helper 默认 30s 超时不够时用；成功后即可删除。
"""
import time
import paramiko
from _creds import HOST, PORT, USER, PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
t0 = time.time()
try:
    client.connect(HOST, PORT, USER, PASSWORD,
                   timeout=90, banner_timeout=90, auth_timeout=90)
    print(f"[SSH 连接成功，耗时 {time.time()-t0:.1f}s]")
    stdin, stdout, stderr = client.exec_command("sync && reboot", timeout=30)
    print("[已发出 sync && reboot，连接将断开]")
    client.close()
except Exception as e:
    print(f"[SSH 连接失败: {type(e).__name__}: {e}]")
