"""启动 docker compose 全栈并做健康检查（长超时，绕开 deploy.py 的 300s 限制）。"""
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import paramiko

from _creds import HOST, PORT, USER, PASSWORD

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
client.get_transport().set_keepalive(15)


def run(cmd: str, timeout: int) -> str:
    print(f"\n>>> {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out)
    if err.strip():
        print("[stderr]", err[:2000])
    if code != 0:
        raise SystemExit(f"命令失败: {cmd}")
    return out


try:
    run("cd /opt/rag-kb && docker compose up -d", timeout=300)
    print("\n=== 等待健康检查（最多 3 分钟）===")
    ok = False
    for i in range(36):
        time.sleep(5)
        t = client.get_transport().open_session()
        t.exec_command("curl -s -m 5 http://localhost:80/api/health || echo EMPTY")
        out = t.makefile().read().decode("utf-8", "replace").strip()
        if out and out != "EMPTY":
            print("✅ 健康检查通过 (端口80):", out)
            ok = True
            break
        t2 = client.get_transport().open_session()
        t2.exec_command("curl -s -m 5 http://localhost:8083/api/health || echo EMPTY")
        out2 = t2.makefile().read().decode("utf-8", "replace").strip()
        if out2 and out2 != "EMPTY":
            print("✅ 健康检查通过 (端口8083):", out2)
            ok = True
            break
    if not ok:
        print("⚠️ 健康检查未通过，查看日志:")
        run("cd /opt/rag-kb && docker compose logs --tail 50 backend", timeout=60)
    # 最终容器状态
    run("docker ps -a --format 'table {{.Names}}\t{{.Status}}'", timeout=30)
finally:
    client.close()
