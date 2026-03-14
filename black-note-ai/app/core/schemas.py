from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"


class AgentRequest(BaseModel):
    task: str
    reset: bool = False


