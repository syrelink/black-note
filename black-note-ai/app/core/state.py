"""
app/core/state.py

按照官方文档 Quickstart 的写法定义 State。

文档原文：
  "The graph's state is used to store the messages and the number of LLM calls.
   State in LangGraph persists throughout the agent's execution.
   The Annotated type with operator.add ensures that new messages are
   appended to the existing list rather than replacing it."

变化点：
  - 文档用 from langchain.messages import AnyMessage，不再用 MessagesState 内置类
  - messages 字段用 Annotated[list[AnyMessage], operator.add] 显式声明
  - 这样更透明，知道 reducer 是 operator.add（追加而不是覆盖）
  - 额外加 user_id 字段供工具函数使用
  - 额外加 llm_calls 字段用于追踪调用次数（文档示例里有这个）
"""

import operator
from typing import Annotated
from typing_extensions import TypedDict
from langchain.messages import AnyMessage


class NoteAgentState(TypedDict):
    # 文档写法：显式声明 reducer
    # operator.add 让新消息追加到列表，而不是覆盖
    messages: Annotated[list[AnyMessage], operator.add]

    # 工具函数做数据隔离需要，跨节点持久存在 → 放进 State
    user_id: str

    # 追踪 LLM 调用次数（参考文档示例，可用于限流）
    llm_calls: int