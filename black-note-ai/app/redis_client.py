"""
app/redis_client.py

单例 Redis 异步客户端，全局共享一个连接池。
auth.py 中的 Redis 连接迁移到这里统一管理。
"""

import redis.asyncio as aioredis
from app.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return _redis
