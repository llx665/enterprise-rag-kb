"""SSH 助手：用 paramiko 连接阿里云服务器执行命令 / 上传文件。

用法：
    python ssh_helper.py exec "uname -a"          # 执行命令
    python ssh_helper.py upload <本地> <远端>       # 上传文件
"""
import sys
import paramiko

# 服务器凭据：从 deploy/server_secrets.py（gitignore）或环境变量读取，不硬编码
from _creds import HOST, PORT, USER, PASSWORD


def get_client() -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
    return client


def run(cmd: str) -> None:
    client = get_client()
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    print(out, end="")
    if err.strip():
        print("[stderr]", err, end="")
    print(f"[exit={code}]")
    client.close()


def upload(local: str, remote: str) -> None:
    client = get_client()
    sftp = client.open_sftp()
    sftp.put(local, remote)
    print(f"上传完成: {local} -> {remote}")
    sftp.close()
    client.close()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "exec":
        run(" ".join(sys.argv[2:]))
    elif len(sys.argv) == 4 and sys.argv[1] == "upload":
        upload(sys.argv[2], sys.argv[3])
    else:
        print("用法: python ssh_helper.py exec '<cmd>' | upload <local> <remote>")
