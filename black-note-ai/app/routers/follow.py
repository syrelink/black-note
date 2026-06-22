"""
app/routers/follow.py  →  /follow/*

对应 Java FollowController，URL 路径完全一致。
"""

from fastapi import APIRouter, Depends

from app.auth import get_request_user_id
from app.common import Result
from app.schemas.follow import FollowUserResponse
from app.services import follow_service

router = APIRouter(prefix="/follow", tags=["关注"])


@router.post("/{user_id}")
async def follow(
    user_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await follow_service.follow(current_user_id, user_id)
    return Result.success()


@router.get("/list/{user_id}")
async def follow_list(user_id: str) -> Result[list[FollowUserResponse]]:
    vos = await follow_service.follow_list(user_id)
    return Result.success(vos)


@router.get("/isFollow/{user_id}")
async def is_follow(
    user_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result[bool]:
    result = await follow_service.is_follow(current_user_id, user_id)
    return Result.success(result)


@router.get("/common/{user_id}")
async def common_follow(
    user_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result[list[FollowUserResponse]]:
    vos = await follow_service.common_follow(current_user_id, user_id)
    return Result.success(vos)
