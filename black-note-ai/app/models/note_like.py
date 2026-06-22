from datetime import datetime

from beanie import Document
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING


class NoteLike(Document):
    user_id:    PydanticObjectId
    note_id:    PydanticObjectId
    created_at: datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "note_likes"
        indexes = [
            IndexModel(
                [("user_id", ASCENDING), ("note_id", ASCENDING)],
                unique=True,
            ),
            IndexModel([("note_id", ASCENDING)]),
        ]
