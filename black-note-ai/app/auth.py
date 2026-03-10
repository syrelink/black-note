from typing import Optional

from fastapi import Header, HTTPException


async def get_request_user_id(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> str:
    """由 SpringBoot 转发时在 header 中注入 X-User-Id。"""
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    raise HTTPException(status_code=401, detail="缺少 X-User-Id，请通过 SpringBoot 转发")

