"""
app/services/note_service.py

笔记 CRUD + 点赞逻辑。

缓存策略（与 Java 一致）：
  - 笔记详情：Redis String，key=note:detail:{id}，TTL 30min
  - 点赞数：  Redis String，key=like:count:{id}
  - 点赞集合：Redis Set，   key=like:set:{id}（存 userId 字符串）

向量同步：发布/更新/删除笔记后，通过 Celery 任务异步执行（唯一真正耗时的操作）。
点赞落库、缓存删除、Feed 推送均在请求内同步完成（耗时 <50ms）。
"""

import json
import logging
from datetime import datetime

from beanie.odm.fields import PydanticObjectId
from beanie.operators import In

from app.common import BusinessException
from app.config import settings
from app.models.note import Note
from app.models.note_like import NoteLike
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.note import NotePublishRequest, NoteResponse

logger = logging.getLogger(__name__)


# ── 内部工具 ──────────────────────────────────────────────────────

def _note_to_response(note: Note, author: User | None, like_count: int, is_liked: bool) -> NoteResponse:
    return NoteResponse(
        id=str(note.id),
        title=note.title,
        content=note.content,
        images=note.images,
        like_count=like_count,
        is_liked=is_liked,
        user_id=str(note.user_id),
        author_name=(author.nickname or author.username) if author else None,
        author_avatar=author.avatar if author else None,
        created_at=note.created_at,
    )


async def _get_like_count(note_id_str: str, note: Note) -> int:
    redis = get_redis()
    key = f"{settings.LIKE_COUNT_KEY}{note_id_str}"
    raw = await redis.get(key)
    if raw is not None:
        return int(raw)
    count = note.like_count or 0
    await redis.set(key, str(count), ex=60 * 60 * 24 * 7)
    return count


async def _get_is_liked(note_id_str: str, user_id: str | None) -> bool:
    if user_id is None:
        return False
    return bool(await get_redis().sismember(f"{settings.LIKE_SET_KEY}{note_id_str}", user_id))


async def _delete_detail_cache(note_id_str: str) -> None:
    try:
        await get_redis().delete(f"{settings.NOTE_DETAIL_KEY}{note_id_str}")
    except Exception as e:
        logger.error("缓存删除失败 note:detail:%s: %s", note_id_str, e)


# ── 公开 API ──────────────────────────────────────────────────────

async def publish(dto: NotePublishRequest, user_id: str) -> Note:
    note = Note(
        user_id=PydanticObjectId(user_id),
        title=dto.title,
        content=dto.content,
        images=dto.images or [],
    )
    await note.insert()
    return note


async def get_note_by_id(note_id: str, user_id: str | None) -> NoteResponse:
    redis = get_redis()
    cache_key = f"{settings.NOTE_DETAIL_KEY}{note_id}"
    cached = await redis.get(cache_key)

    if cached is not None:
        if cached == "":
            raise BusinessException(404, "笔记不存在")
        vo = NoteResponse(**json.loads(cached))
        # Refresh live like data
        note = await Note.get(PydanticObjectId(note_id))
        if note:
            vo.like_count = await _get_like_count(note_id, note)
            vo.is_liked   = await _get_is_liked(note_id, user_id)
        return vo

    note = await Note.get(PydanticObjectId(note_id))
    if not note or note.is_deleted:
        await redis.set(cache_key, "", ex=settings.CACHE_NULL_TTL_MINUTES * 60)
        raise BusinessException(404, "笔记不存在")

    author     = await User.get(note.user_id)
    like_count = await _get_like_count(note_id, note)
    is_liked   = await _get_is_liked(note_id, user_id)
    vo = _note_to_response(note, author, like_count, is_liked)

    cache_data = vo.model_copy(update={"like_count": note.like_count or 0, "is_liked": False})
    await redis.set(cache_key, cache_data.model_dump_json(), ex=settings.CACHE_TTL_MINUTES * 60)
    return vo


async def update_note(note_id: str, dto: NotePublishRequest, user_id: str) -> None:
    note = await Note.get(PydanticObjectId(note_id))
    if not note or note.is_deleted:
        raise BusinessException(404, "笔记不存在")
    if str(note.user_id) != user_id:
        raise BusinessException(403, "无权编辑此笔记")

    note.title      = dto.title
    note.content    = dto.content
    note.images     = dto.images or []
    note.updated_at = datetime.now()
    await note.save()
    await _delete_detail_cache(note_id)


async def delete_note(note_id: str, user_id: str) -> None:
    note = await Note.get(PydanticObjectId(note_id))
    if not note or note.is_deleted:
        raise BusinessException(404, "笔记不存在")
    if str(note.user_id) != user_id:
        raise BusinessException(403, "无权删除此笔记")

    note.is_deleted = True
    note.updated_at = datetime.now()
    await note.save()
    await _delete_detail_cache(note_id)


async def note_list(page: int, size: int, user_id: str | None) -> list[NoteResponse]:
    offset = (page - 1) * size
    notes = await (
        Note.find(Note.is_deleted == False)
        .sort(-Note.created_at)
        .skip(offset)
        .limit(size)
        .to_list()
    )
    return await _batch_convert(notes, user_id)


async def list_by_user(target_user_id: str, current_user_id: str | None) -> list[NoteResponse]:
    notes = await (
        Note.find(
            Note.user_id == PydanticObjectId(target_user_id),
            Note.is_deleted == False,
        )
        .sort(-Note.created_at)
        .to_list()
    )
    return await _batch_convert(notes, current_user_id)


async def _batch_convert(notes: list[Note], user_id: str | None) -> list[NoteResponse]:
    if not notes:
        return []
    user_oids = list({note.user_id for note in notes})
    users = await User.find(In(User.id, user_oids)).to_list()
    user_map = {u.id: u for u in users}

    result = []
    for note in notes:
        note_id_str = str(note.id)
        author      = user_map.get(note.user_id)
        like_count  = await _get_like_count(note_id_str, note)
        is_liked    = await _get_is_liked(note_id_str, user_id)
        result.append(_note_to_response(note, author, like_count, is_liked))
    return result


# ── 点赞（Redis 先行，同步落库）────────────────────────────────────

async def like(note_id: str, user_id: str) -> None:
    redis = get_redis()
    like_set_key   = f"{settings.LIKE_SET_KEY}{note_id}"
    like_count_key = f"{settings.LIKE_COUNT_KEY}{note_id}"

    if not await redis.exists(like_count_key):
        note = await Note.get(PydanticObjectId(note_id))
        if not note:
            raise BusinessException(404, "笔记不存在")
        await redis.set(like_count_key, str(note.like_count or 0), ex=60 * 60 * 24 * 7)

    is_member = await redis.sismember(like_set_key, user_id)

    if is_member:
        await redis.srem(like_set_key, user_id)
        await redis.decr(like_count_key)
        await _db_cancel_like(note_id, user_id)
    else:
        await redis.sadd(like_set_key, user_id)
        await redis.incr(like_count_key)
        await _db_add_like(note_id, user_id)


async def _db_add_like(note_id: str, user_id: str) -> None:
    note_oid = PydanticObjectId(note_id)
    user_oid = PydanticObjectId(user_id)
    if await NoteLike.find_one(NoteLike.note_id == note_oid, NoteLike.user_id == user_oid):
        return
    await NoteLike(note_id=note_oid, user_id=user_oid).insert()
    await Note.find_one(Note.id == note_oid).update({"$inc": {"like_count": 1}})


async def _db_cancel_like(note_id: str, user_id: str) -> None:
    note_oid = PydanticObjectId(note_id)
    user_oid = PydanticObjectId(user_id)
    record = await NoteLike.find_one(NoteLike.note_id == note_oid, NoteLike.user_id == user_oid)
    if record:
        await record.delete()
        # Decrement but floor at 0 via conditional update
        await Note.find_one(Note.id == note_oid, Note.like_count > 0).update(
            {"$inc": {"like_count": -1}}
        )


async def get_like_count(note_id: str) -> int:
    note = await Note.get(PydanticObjectId(note_id))
    if not note:
        raise BusinessException(404, "笔记不存在")
    return await _get_like_count(note_id, note)


async def is_liked(note_id: str, user_id: str | None) -> bool:
    return await _get_is_liked(note_id, user_id)
