"""安全工具：密码哈希 + JWT 令牌。

- 密码使用 bcrypt 加盐哈希存储，绝不保存明文。
- JWT 采用 HS256，access token（短期）+ refresh token（长期）双令牌机制。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from ..config import settings


def hash_password(password: str) -> str:
    """bcrypt 加盐哈希。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def _create_token(subject: str, expires_minutes: int, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,                # 用户 ID
        "type": token_type,            # access / refresh
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.TOKEN_ALGORITHM)


def create_access_token(user_id: int) -> str:
    """短期访问令牌。"""
    return _create_token(str(user_id), settings.ACCESS_TOKEN_EXPIRE_MINUTES, "access")


def create_refresh_token(user_id: int) -> str:
    """长期刷新令牌。"""
    return _create_token(
        str(user_id),
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60,
        "refresh",
    )


def decode_token(token: str) -> dict:
    """解码并校验 JWT，返回 payload；无效则抛 jwt.PyJWTError。"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.TOKEN_ALGORITHM])
