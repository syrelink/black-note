"""
app/routers/user.py  →  /user/*

对应 Java UserController，URL 路径完全一致。
"""

from fastapi import APIRouter, Depends

from app.auth import get_request_user_id
from app.common import Result
from app.schemas.user import LoginRequest, LoginResponse, RegisterRequest, UserResponse, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/user", tags=["用户"])


@router.post("/register")
async def register(dto: RegisterRequest) -> Result:
    await user_service.register(dto)
    return Result.success()


@router.post("/login")
async def login(dto: LoginRequest) -> Result[LoginResponse]:
    vo = await user_service.login(dto)
    return Result.success(vo)


@router.get("/{user_id}")
async def get_user(user_id: str) -> Result[UserResponse]:
    vo = await user_service.get_user_by_id(user_id)
    return Result.success(vo)


@router.put("/me")
async def update_me(
    dto: UserUpdateRequest,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await user_service.update_me(current_user_id, dto)
    return Result.success()
