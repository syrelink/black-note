"""
app/auth.py

Token 认证依赖项。
Redis key 格式 login:token:{token} → userId，与 Java 端完全一致，
前端无需任何改动即可对接。

提供两个 FastAPI 依赖：
  - get_request_user_id : 必须登录，否则 401
  - get_optional_user_id: 未登录时返回 None（公开接口用）
"""

from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings
from app.redis_client import get_redis


async def get_request_user_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    if not authorization or not authorization.strip():
        raise HTTPException(status_code=401, detail="缺少 Authorization token")

    token = authorization.strip()
    redis_key = f"{settings.TOKEN_KEY_PREFIX}{token}"

    try:
        user_id = await get_redis().get(redis_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis 连接失败: {e}")

    if not user_id:
        raise HTTPException(status_code=401, detail="token 无效或已过期，请重新登录")

    await get_redis().expire(redis_key, settings.TOKEN_TTL_SECONDS)
    return str(user_id)


async def get_optional_user_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    """公开接口使用：未登录时返回 None，不抛 401。"""
    if not authorization or not authorization.strip():
        return None
    try:
        return await get_request_user_id(authorization)
    except HTTPException:
        return None
