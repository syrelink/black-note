"""
app/services/feed_service.py

Feed 流（推模型）。

收件箱：Redis ZSet，key=feed:inbox:{userId}，value=noteId，score=时间戳。
push_to_fans 在发布笔记后同步执行（Redis ZADD，耗时 <10ms，不值得异步化）。
"""

import time

from beanie.odm.fields import PydanticObjectId
from beanie.operators import In

from app.config import settings
from app.models.follow import Follow
from app.models.note import Note
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.feed import FeedResponse
from app.schemas.note import NoteResponse


async def get_feed(current_user_id: str, last_timestamp: int, page_size: int) -> FeedResponse:
    redis = get_redis()
    inbox_key = f"{settings.FEED_INBOX_KEY}{current_user_id}"
    max_score  = last_timestamp if last_timestamp > 0 else int(time.time() * 1000)

    tuples = await redis.zrevrangebyscore(
        inbox_key, max_score, 0,
        start=0, num=page_size,
        withscores=True,
    )

    if not tuples:
        return FeedResponse()

    note_id_strs: list[str] = []
    next_timestamp = 0
    for value, score in tuples:
        note_id_strs.append(value if isinstance(value, str) else value.decode())
        next_timestamp = int(score)

    note_oids = [PydanticObjectId(nid) for nid in note_id_strs]
    notes_list = await Note.find(In(Note.id, note_oids), Note.is_deleted == False).to_list()
    notes_map  = {str(n.id): n for n in notes_list}

    user_oids = list({n.user_id for n in notes_list})
    users = await User.find(In(User.id, user_oids)).to_list()
    user_map = {u.id: u for u in users}

    note_vos: list[NoteResponse] = []
    for nid_str in note_id_strs:
        note = notes_map.get(nid_str)
        if not note:
            continue
        author = user_map.get(note.user_id)
        note_vos.append(NoteResponse(
            id=str(note.id),
            title=note.title,
            content=note.content,
            images=note.images,
            like_count=note.like_count or 0,
            is_liked=False,
            user_id=str(note.user_id),
            author_name=(author.nickname or author.username) if author else None,
            author_avatar=author.avatar if author else None,
            created_at=note.created_at,
        ))

    return FeedResponse(
        notes=note_vos,
        next_timestamp=next_timestamp,
        has_more=len(tuples) == page_size,
    )


async def push_to_fans(note_id: str, author_id: str) -> None:
    """将笔记推送到作者所有粉丝的收件箱。"""
    redis = get_redis()
    fans = await Follow.find(Follow.follow_user_id == PydanticObjectId(author_id)).to_list()
    if not fans:
        return

    timestamp = int(time.time() * 1000)
    for fan in fans:
        await redis.zadd(
            f"{settings.FEED_INBOX_KEY}{fan.user_id}",
            {note_id: timestamp},
        )
