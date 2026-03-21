from typing import Annotated
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class NoteAgentState(TypedDict):
    messages:  Annotated[list, add_messages]  # 消息列表，自动合并
    llm_calls: int                             # LLM 调用计数
    summary:   str                             # 历史对话摘要（压缩后保留）