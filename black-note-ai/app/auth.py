from typing import Optional
import redis.asyncio as aioredis
import os
from fastapi import Header, HTTPException, Request
from dotenv import load_dotenv

load_dotenv()

# Redis 连接（
_redis: Optional[aioredis.Redis] = None

def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
    return _redis


async def get_request_user_id(
    request: Request,       # FastAPI自动注入请求对象（这里没用到，可以删）
    authorization: Optional[str] = Header(default=None, alias="Authorization"),  # 自动从请求头取值
    # 自动从请求头里取 Authorization 字段的值，取不到就是 None
) -> str:
    """
    前端带 Authorization: {token} 直接调 FastAPI 即可。
    """
    token = authorization

    # 如果请求头里没有 Authorization，直接返回401
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="缺少 Authorization token")

    # 拼接Redis的key，格式和Spring Boot存的一样
    token = token.strip()
    redis_key = f"login:token:{token}"

    try:
        # 去Redis查这个key对应的值，login:token:{token} → userId
        user_id = await get_redis().get(redis_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis连接失败: {e}")
        
    # 查出来是None，说明token不存在或者已过期，返回401
    if not user_id:
        raise HTTPException(status_code=401, detail="token无效或已过期，请重新登录")

    await get_redis().expire(redis_key, 60 * 60)

    return str(user_id)