from pydantic import BaseModel


class FollowUserResponse(BaseModel):
    id:       str        # MongoDB ObjectId hex string
    username: str
    nickname: str | None = None
    avatar:   str | None = None
