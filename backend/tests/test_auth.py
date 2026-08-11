"""认证与权限接口测试（TestClient 全链路）。"""
from fastapi.testclient import TestClient


def _register(client: TestClient, username: str, password: str = "pass123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )


def _login(client: TestClient, username: str, password: str = "pass123"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- 注册 / 登录 / 当前用户 ----------
def test_register_login_me(client):
    r = _register(client, "tester1")
    assert r.status_code in (200, 201)

    r = _login(client, "tester1")
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["username"] == "tester1"
    assert data["user"]["role"] == "user"  # 注册用户一律普通角色

    me = client.get("/api/auth/me", headers=_auth_headers(data["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "tester1"


def test_duplicate_username_rejected(client):
    _register(client, "dup_user")
    r = _register(client, "dup_user")
    assert r.status_code == 409


def test_wrong_password_rejected(client):
    _register(client, "tester2")
    r = _login(client, "tester2", "wrongpass")
    assert r.status_code == 401


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/register", json={"username": "shortpw", "password": "123"}
    )
    assert r.status_code == 422


def test_unauthenticated_me(client):
    assert client.get("/api/auth/me").status_code == 401


# ---------- 修改密码 ----------
def test_change_password_flow(client):
    _register(client, "tester3", "oldpass")
    r = _login(client, "tester3", "oldpass")
    token = r.json()["access_token"]

    # 原密码错误 -> 400
    r = client.put(
        "/api/auth/password",
        json={"old_password": "nope", "new_password": "newpass"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 400

    # 正确修改
    r = client.put(
        "/api/auth/password",
        json={"old_password": "oldpass", "new_password": "newpass"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 200

    # 旧密码失效，新密码可登录
    assert _login(client, "tester3", "oldpass").status_code == 401
    assert _login(client, "tester3", "newpass").status_code == 200


# ---------- 管理员权限 ----------
def test_admin_seeded(client):
    """lifespan 自动种子内置管理员 admin/123456。"""
    r = _login(client, "admin", "123456")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"


def test_kb_admin_only(client):
    """知识库接口仅管理员可访问：未登录 401，普通用户 403，管理员 200。"""
    assert client.get("/api/kb/documents").status_code == 401

    _register(client, "tester4")
    r = _login(client, "tester4")
    headers = _auth_headers(r.json()["access_token"])
    assert client.get("/api/kb/documents", headers=headers).status_code == 403

    r = _login(client, "admin", "123456")
    headers = _auth_headers(r.json()["access_token"])
    assert client.get("/api/kb/documents", headers=headers).status_code == 200


# ---------- 健康检查 ----------
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
