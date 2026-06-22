"""
app/services/chat_session_service.py

AI 对话会话的持久化管理（CRUD）。
存储在 MongoDB chat_sessions 集合，session_id 字段存 LangGraph UUID。
"""

from datetime import datetime

from beanie.odm.fields import PydanticObjectId

from app.models.chat_session import ChatSession
from app.schemas.chat_session import ChatSessionResponse


def _to_response(s: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        session_id=s.session_id,
        user_id=str(s.user_id),
        title=s.title,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def get_by_user_id(user_id: str) -> list[ChatSessionResponse]:
    sessions = await (
        ChatSession.find(ChatSession.user_id == PydanticObjectId(user_id))
        .sort(-ChatSession.updated_at)
        .to_list()
    )
    return [_to_response(s) for s in sessions]


async def upsert(session_id: str, user_id: str, title: str) -> None:
    existing = await ChatSession.find_one(ChatSession.session_id == session_id)
    if existing is None:
        await ChatSession(
            session_id=session_id,
            user_id=PydanticObjectId(user_id),
            title=title,
        ).insert()
    else:
        existing.title      = title
        existing.updated_at = datetime.now()
        await existing.save()


async def delete_session(session_id: str, user_id: str) -> None:
    record = await ChatSession.find_one(
        ChatSession.session_id == session_id,
        ChatSession.user_id == PydanticObjectId(user_id),
    )
    if record:
        await record.delete()
