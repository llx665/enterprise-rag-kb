"""服务器凭据加载器（本文件不含任何真实密码）。

真实凭据存于 deploy/server_secrets.py（已 gitignore，不会提交），
用 importlib 按绝对路径加载，避免「deploy 目录」与 scripts/deploy.py 重名冲突；
也可通过环境变量 ALIYUN_HOST / ALIYUN_USER / ALIYUN_PASSWORD 提供。

用法：
    from _creds import HOST, PORT, USER, PASSWORD
"""
import importlib.util
import os
import sys


def _load_secrets_file(path: str):
    """按绝对路径加载凭据文件：无模块名冲突、不进入 sys.modules 缓存。"""
    spec = importlib.util.spec_from_file_location("_server_secrets", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load():
    # scripts/ 的上级即项目根目录
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    secrets_path = os.path.join(root, "deploy", "server_secrets.py")
    try:
        mod = _load_secrets_file(secrets_path)
        return mod.HOST, mod.PORT, mod.USER, mod.PASSWORD
    except Exception:
        host = os.environ.get("ALIYUN_HOST", "47.101.151.35")
        port = int(os.environ.get("ALIYUN_PORT", "22"))
        user = os.environ.get("ALIYUN_USER", "root")
        password = os.environ.get("ALIYUN_PASSWORD", "")
        if not password:
            raise SystemExit(
                f"缺少服务器密码：请创建 {secrets_path}（参考 "
                "server_secrets.example.py），或设置环境变量 ALIYUN_PASSWORD"
            )
        return host, port, user, password


HOST, PORT, USER, PASSWORD = _load()
