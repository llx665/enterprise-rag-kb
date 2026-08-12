"""一次性脚本：把本地导出的 ONNX 向量模型上传到服务器 /opt/rag-kb/models/。

容器挂载 ./models -> /models，首次启动若 model.onnx 存在则跳过在线下载。
只上传 ONNX 推理所需文件（model.onnx / model.onnx.data / tokenizer.json / 小配置），
跳过 model.safetensors 与 pytorch_model.bin（各 95MB 基础权重，ONNX 运行时不需要）。
"""
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import paramiko

from _creds import HOST, PORT, USER, PASSWORD

REMOTE_DIR = "/opt/rag-kb/models/bge-small-zh-v1.5"
LOCAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "infra/models/bge-small-zh-v1.5",
)
# 跳过的基础权重（ONNX Runtime 用不到）
SKIP = {"model.safetensors", "pytorch_model.bin", "README.md", ".gitattributes"}

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, PORT, USER, PASSWORD, timeout=30)
client.get_transport().set_keepalive(15)
# 先确保目录存在（SFTP 无 makedirs，用 shell 递归建）
client.exec_command(f"mkdir -p {REMOTE_DIR}", timeout=30)[1].read()
sftp = client.open_sftp()

total = 0
for root, dirs, files in os.walk(LOCAL_DIR):
    rel = os.path.relpath(root, LOCAL_DIR)
    target = REMOTE_DIR if rel == "." else f"{REMOTE_DIR}/{rel.replace(os.sep, '/')}"
    try:
        sftp.stat(target)
    except IOError:
        sftp.mkdir(target)
    for f in files:
        if f in SKIP:
            print(f"  跳过: {f}")
            continue
        lp = os.path.join(root, f)
        rp = f"{target}/{f}"
        size = os.path.getsize(lp)
        for attempt in range(1, 4):
            try:
                sftp.put(lp, rp)
                print(f"  ✅ {f} ({size/1024/1024:.1f}MB)")
                total += size
                break
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ {f} 上传失败(第{attempt}次): {e}")
                if attempt == 3:
                    raise
                time.sleep(3 * attempt)

print(f"\n模型上传完成，共 {total/1024/1024:.1f}MB -> {REMOTE_DIR}")
sftp.close()
client.close()
