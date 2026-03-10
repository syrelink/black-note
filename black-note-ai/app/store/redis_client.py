import os
from typing import Optional

from redis.asyncio import ConnectionPool, Redis


def _build_redis_url() -> str:
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    if os.getenv("REDIS_PASSWORD"):
        host = os.getenv("REDIS_HOST", "127.0.0.1")
        port = os.getenv("REDIS_PORT", "6379")
        password = os.getenv("REDIS_PASSWORD")
        redis_url = f"redis://:{password}@{host}:{port}/0"
    return redis_url


pool = ConnectionPool.from_url(_build_redis_url(), decode_responses=True)
redis_client: Redis = Redis(connection_pool=pool)


async def get_user_id_by_token(token: str) -> Optional[str]:
    """复用 SpringBoot：login:token:<token> -> userId。"""
    if not token or not token.strip():
        return None
    return await redis_client.get(f"login:token:{token.strip()}")

