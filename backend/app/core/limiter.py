"""接口限流器（慢速滥用防护）。

- 存储：配置 REDIS_URL 时用 Redis 存储（生产多实例共享计数），否则内存实现
- 生产环境建议在 Nginx 层再做一层基于 IP 的连接级限流，双保险
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL or "memory://",
    enabled=settings.RATE_LIMIT_ENABLED,
)
