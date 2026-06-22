from datetime import datetime

from beanie import Document
from beanie.odm.fields import PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING


class Follow(Document):
    user_id:        PydanticObjectId
    follow_user_id: PydanticObjectId
    created_at:     datetime = Field(default_factory=datetime.now)

    class Settings:
        name = "follows"
        indexes = [
            IndexModel(
                [("user_id", ASCENDING), ("follow_user_id", ASCENDING)],
                unique=True,
            ),
            IndexModel([("follow_user_id", ASCENDING)]),
        ]
