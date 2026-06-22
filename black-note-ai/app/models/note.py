from datetime import datetime

from beanie import Document
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING, DESCENDING


class Note(Document):
    user_id:    PydanticObjectId
    title:      str
    content:    str | None = None
    images:     list[str] = []          # native array, not comma-string
    like_count: int = 0
    is_deleted: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "notes"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("is_deleted", ASCENDING), ("created_at", DESCENDING)]),
        ]
