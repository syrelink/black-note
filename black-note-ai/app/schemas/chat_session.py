from datetime import datetime
from pydantic import BaseModel


class ChatSessionUpsertRequest(BaseModel):
    title: str = "新对话"


class ChatSessionResponse(BaseModel):
    session_id: str
    user_id:    str
    title:      str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
