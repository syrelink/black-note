"""
app/services/user_service.py

用户注册、登录、信息查询与更新。
Token 以 UUID 存入 Redis，key 格式与 Java 端完全一致：login:token:{token} → userId
"""

import uuid
from datetime import datetime

from passlib.context import CryptContext

from app.common import BusinessException
from app.config import settings
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.user import LoginRequest, LoginResponse, RegisterRequest, UserResponse, UserUpdateRequest

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def register(dto: RegisterRequest) -> None:
    if await User.find_one(User.username == dto.username):
        raise BusinessException(400, "用户名已存在")

    user = User(
        username=dto.username,
        password=_pwd_ctx.hash(dto.password),
        nickname="小黑子",
        avatar=settings.DEFAULT_AVATAR,
    )
    await user.insert()


async def login(dto: LoginRequest) -> LoginResponse:
    user = await User.find_one(User.username == dto.username)
    if not user or not _pwd_ctx.verify(dto.password, user.password):
        raise BusinessException(400, "用户名或密码错误")

    token = uuid.uuid4().hex
    redis = get_redis()
    await redis.set(
        f"{settings.TOKEN_KEY_PREFIX}{token}",
        str(user.id),
        ex=settings.TOKEN_TTL_SECONDS,
    )

    return LoginResponse(
        token=token,
        id=str(user.id),
        username=user.username,
        nickname=user.nickname,
        avatar=user.avatar,
    )


async def get_user_by_id(user_id: str) -> UserResponse:
    from beanie.odm.fields import PydanticObjectId
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise BusinessException(404, "用户不存在")
    return UserResponse(id=str(user.id), username=user.username, nickname=user.nickname, avatar=user.avatar)


async def update_me(user_id: str, dto: UserUpdateRequest) -> None:
    from beanie.odm.fields import PydanticObjectId
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise BusinessException(404, "用户不存在")

    if dto.nickname is not None:
        user.nickname = dto.nickname
    if dto.avatar is not None:
        user.avatar = dto.avatar
    user.updated_at = datetime.now()
    await user.save()
