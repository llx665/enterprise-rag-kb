"""把本地 bge 向量模型上传到服务器挂载卷，避免容器内重新下载。

用法：
    cd backend && .venv/Scripts/python.exe ../scripts/upload_model.py
"""
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import paramiko

# 服务器凭据：从 deploy/server_secrets.py（gitignore）或环境变量读取，不硬编码
from _creds import HOST, PORT, USER, PASSWORD

REMOTE_MODEL_DIR = "/opt/rag-kb/models/bge-small-zh-v1.5"
LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "infra", "models", "bge-small-zh-v1.5",
)
# 跳过冗余文件：pytorch_model.bin 与 model.safetensors 二选一，留 safetensors
SKIP = {"pytorch_model.bin", ".gitattributes", "README.md"}


def upload_dir(client, sftp, local: str, remote: str) -> None:
    """递归上传，单文件失败重试。"""
    for root, dirs, files in os.walk(local):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        rel = os.path.relpath(root, local)
        target = remote if rel == "." else f"{remote}/{rel.replace(os.sep, '/')}"
        try:
            sftp.stat(target)
        except IOError:
            sftp.mkdir(target)
        for f in files:
            if f in SKIP:
                continue
            lp = os.path.join(root, f)
            rp = f"{target}/{f}"
            for attempt in range(1, 5):
                try:
                    sftp.put(lp, rp)
                    print(f"  ✅ {f} ({os.path.getsize(lp)//1024//1024}MB)")
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"  ⚠️ {f} 失败(第{attempt}次): {e}")
                    if attempt == 4:
                        raise
                    time.sleep(5 * attempt)
                    try:
                        sftp.close()
                    except Exception:
                        pass
                    sftp = client.open_sftp()


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
    client.get_transport().set_keepalive(15)
    sftp = client.open_sftp()
    i, o, e = client.exec_command("mkdir -p /opt/rag-kb/models", timeout=30)
    o.read()
    print(f"上传模型 {LOCAL_MODEL_DIR} -> {REMOTE_MODEL_DIR}")
    upload_dir(client, sftp, LOCAL_MODEL_DIR, REMOTE_MODEL_DIR)
    sftp.close()
    client.close()
    print("✅ 模型上传完成")


if __name__ == "__main__":
    main()
