"""
app/services/follow_service.py

关注/取消关注，关注列表，共同关注。

Redis Set key=follow:{userId} 存所有被关注用户的 ID 字符串，
与 Java FollowServiceImpl 的 FOLLOW_KEY 完全一致。
"""

from beanie.odm.fields import PydanticObjectId
from beanie.operators import In

from app.config import settings
from app.models.follow import Follow
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.follow import FollowUserResponse


def _user_to_response(u: User) -> FollowUserResponse:
    return FollowUserResponse(id=str(u.id), username=u.username, nickname=u.nickname, avatar=u.avatar)


async def follow(current_user_id: str, target_user_id: str) -> None:
    redis = get_redis()
    follow_key = f"{settings.FOLLOW_KEY}{current_user_id}"

    is_following = await redis.sismember(follow_key, target_user_id)

    if is_following:
        cur_oid    = PydanticObjectId(current_user_id)
        target_oid = PydanticObjectId(target_user_id)
        record = await Follow.find_one(
            Follow.user_id == cur_oid,
            Follow.follow_user_id == target_oid,
        )
        if record:
            await record.delete()
        await redis.srem(follow_key, target_user_id)
    else:
        await Follow(
            user_id=PydanticObjectId(current_user_id),
            follow_user_id=PydanticObjectId(target_user_id),
        ).insert()
        await redis.sadd(follow_key, target_user_id)


async def is_follow(current_user_id: str, target_user_id: str) -> bool:
    return bool(await get_redis().sismember(f"{settings.FOLLOW_KEY}{current_user_id}", target_user_id))


async def follow_list(user_id: str) -> list[FollowUserResponse]:
    redis = get_redis()
    ids = await redis.smembers(f"{settings.FOLLOW_KEY}{user_id}")
    if not ids:
        return []
    oids = [PydanticObjectId(i) for i in ids]
    users = await User.find(In(User.id, oids)).to_list()
    return [_user_to_response(u) for u in users]


async def common_follow(current_user_id: str, target_user_id: str) -> list[FollowUserResponse]:
    redis = get_redis()
    common_ids = await redis.sinter(
        f"{settings.FOLLOW_KEY}{current_user_id}",
        f"{settings.FOLLOW_KEY}{target_user_id}",
    )
    if not common_ids:
        return []
    oids = [PydanticObjectId(i) for i in common_ids]
    users = await User.find(In(User.id, oids)).to_list()
    return [_user_to_response(u) for u in users]
