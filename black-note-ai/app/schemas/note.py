from datetime import datetime
from pydantic import BaseModel, field_validator


class NotePublishRequest(BaseModel):
    title:   str
    content: str | None = None
    images:  list[str] | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("标题不能为空")
        return v.strip()


class NoteResponse(BaseModel):
    id:            str            # MongoDB ObjectId hex string
    title:         str
    content:       str | None = None
    images:        list[str] = []  # MongoDB 原生数组，不再是逗号字符串
    like_count:    int = 0
    is_liked:      bool = False
    user_id:       str            # MongoDB ObjectId hex string
    author_name:   str | None = None
    author_avatar: str | None = None
    created_at:    datetime | None = None
