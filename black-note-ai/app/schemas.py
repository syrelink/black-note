from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str = "default"


class AgentRequest(BaseModel):
    task: str
    user_id: str


class SyncRequest(BaseModel):
    note_id: int


class DeleteRequest(BaseModel):
    note_id: int

