"""
app/routers/note.py  →  /note/*

对应 Java NoteController，URL 路径完全一致。

向量同步通过 Celery 任务异步执行（唯一耗时操作）。
Feed 推送和点赞落库在请求内同步完成（耗时 <50ms）。
"""

from fastapi import APIRouter, Depends

from app.auth import get_optional_user_id, get_request_user_id
from app.common import Result
from app.schemas.note import NotePublishRequest, NoteResponse
from app.services import feed_service, note_service
from app.tasks import vector_sync

router = APIRouter(prefix="/note", tags=["笔记"])


@router.post("/publish")
async def publish(
    dto: NotePublishRequest,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    note = await note_service.publish(dto, current_user_id)
    note_id = str(note.id)
    await feed_service.push_to_fans(note_id, current_user_id)
    vector_sync.delay(note_id, "sync")
    return Result.success()


@router.get("/list")
async def note_list(
    page: int = 1,
    size: int = 20,
    current_user_id: str | None = Depends(get_optional_user_id),
) -> Result[list[NoteResponse]]:
    vos = await note_service.note_list(page, size, current_user_id)
    return Result.success(vos)


@router.get("/list/{user_id}")
async def list_by_user(
    user_id: str,
    current_user_id: str | None = Depends(get_optional_user_id),
) -> Result[list[NoteResponse]]:
    vos = await note_service.list_by_user(user_id, current_user_id)
    return Result.success(vos)


@router.get("/{note_id}")
async def get_note(
    note_id: str,
    current_user_id: str | None = Depends(get_optional_user_id),
) -> Result[NoteResponse]:
    vo = await note_service.get_note_by_id(note_id, current_user_id)
    return Result.success(vo)


@router.put("/update/{note_id}")
async def update_note(
    note_id: str,
    dto: NotePublishRequest,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await note_service.update_note(note_id, dto, current_user_id)
    vector_sync.delay(note_id, "sync")
    return Result.success()


@router.delete("/delete/{note_id}")
async def delete_note(
    note_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await note_service.delete_note(note_id, current_user_id)
    vector_sync.delay(note_id, "delete")
    return Result.success()


@router.post("/like/{note_id}")
async def like(
    note_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await note_service.like(note_id, current_user_id)
    return Result.success()


@router.get("/like/count/{note_id}")
async def get_like_count(note_id: str) -> Result[int]:
    count = await note_service.get_like_count(note_id)
    return Result.success(count)


@router.get("/like/status/{note_id}")
async def is_liked(
    note_id: str,
    current_user_id: str | None = Depends(get_optional_user_id),
) -> Result[bool]:
    liked = await note_service.is_liked(note_id, current_user_id)
    return Result.success(liked)
