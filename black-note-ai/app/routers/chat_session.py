"""
app/routers/chat_session.py  →  /chat/sessions/*

对应 Java ChatSessionController，URL 路径完全一致。
"""

from fastapi import APIRouter, Depends

from app.auth import get_request_user_id
from app.common import Result
from app.schemas.chat_session import ChatSessionResponse, ChatSessionUpsertRequest
from app.services import chat_session_service

router = APIRouter(prefix="/chat/sessions", tags=["AI 会话"])


@router.get("")
async def get_sessions(
    current_user_id: str = Depends(get_request_user_id),
) -> Result[list[ChatSessionResponse]]:
    sessions = await chat_session_service.get_by_user_id(current_user_id)
    return Result.success(sessions)


@router.post("/{session_id}")
async def upsert_session(
    session_id: str,
    body: ChatSessionUpsertRequest,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await chat_session_service.upsert(session_id, current_user_id, body.title)
    return Result.success()


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user_id: str = Depends(get_request_user_id),
) -> Result:
    await chat_session_service.delete_session(session_id, current_user_id)
    return Result.success()
