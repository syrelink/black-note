from pydantic import BaseModel
from typing import TypedDict

class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"


class AgentRequest(BaseModel):
    task: str
    reset: bool = False


class AgentContext(TypedDict):
    user_id: str
    some_other_info: str | None
