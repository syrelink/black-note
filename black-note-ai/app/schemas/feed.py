from pydantic import BaseModel
from app.schemas.note import NoteResponse


class FeedResponse(BaseModel):
    list: list[NoteResponse] = []
    next_timestamp: int = 0
    has_more: bool = False
