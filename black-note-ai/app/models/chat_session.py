from datetime import datetime

from beanie import Document, Indexed
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, DESCENDING


class ChatSession(Document):
    # LangGraph UUID string — stored as regular field, not _id
    session_id: Indexed(str, unique=True)
    user_id:    PydanticObjectId
    title:      str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "chat_sessions"
        indexes = [
            IndexModel([("user_id", DESCENDING), ("updated_at", DESCENDING)]),
        ]
