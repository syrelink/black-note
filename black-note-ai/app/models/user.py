from datetime import datetime

from beanie import Document, Indexed
from pydantic import Field


class User(Document):
    username:   Indexed(str, unique=True)
    password:   str
    nickname:   str | None = None
    avatar:     str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "users"
