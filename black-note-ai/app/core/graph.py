"""
app/core/graph.py

严格按照官方文档 Quickstart（Graph API）写法实现。

文档关键写法（和旧版不同的地方）：

1. 工具节点手写，不用 ToolNode：
   文档里 tool_node 自己遍历 tool_calls，用 tools_by_name 字典查找执行，
   返回 ToolMessage 列表。

2. 条件边第三个参数传列表，不传字典：
   agent_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
   文档原文就是这样写的。

3. 节点命名跟文档一致：
   - LLM 节点叫 "llm_call"（文档里叫这个）
   - 工具节点叫 "tool_node"（文档里叫这个）

4. llm_calls 计数跟文档示例一致：
   每次调用 LLM 时 +1，记录在 State 里。

5. Streaming 用 version="v2"：
   文档明确说 "All examples on this page use version='v2'"
   chunk 格式变成 {"type": ..., "data": ...}
"""

import os
import sqlite3
from typing import Literal
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langchain.messages import SystemMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import RetryPolicy

from app.core.state import NoteAgentState
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.core.tools import make_tools

load_dotenv()

# ── 持久化（全局单例）────────────────────────────────────────
_conn = sqlite3.connect("./checkpoints.db", check_same_thread=False)
_checkpointer = SqliteSaver(_conn)


def build_graph(vectorstore):
    """
    按文档 Quickstart Graph API 写法构建图。
    应用启动时调用一次，返回 compiled graph。
    """

    # ── Step1：初始化模型和工具 ───────────────────────────
    # 文档写法：init_chat_model（通用初始化函数，支持多种模型）
    model = init_chat_model(
        os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        model_provider="openai",   # DeepSeek 兼容 OpenAI 接口
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.3,
    )

    tools, tools_by_name = make_tools(vectorstore)
    model_with_tools = model.bind_tools(tools)

    # ── Step2：定义 model 节点（LLM step）────────────────
    # 文档写法：节点函数命名为 llm_call
    def llm_call(state: NoteAgentState):
        """LLM decides whether to call a tool or not"""
        return {
            "messages": [
                model_with_tools.invoke(
                    [SystemMessage(content=ROVER_SYSTEM_PROMPT)]
                    + state["messages"]
                )
            ],
            # 文档示例里有这个，每次 LLM 调用 +1
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    # ── Step3：定义 tool 节点（Data step）────────────────
    # 文档写法：手写 tool_node，自己遍历 tool_calls
    # 不用 ToolNode，更透明更好理解
    def tool_node(state: NoteAgentState):
        """Performs the tool call"""
        result = []
        for tool_call in state["messages"][-1].tool_calls:
            # 从 tools_by_name 字典里找到对应工具
            tool = tools_by_name[tool_call["name"]]
            # 执行工具，传入 tool_call（含 args 和 id）
            observation = tool.invoke(tool_call["args"])
            # 包成 ToolMessage 追加到 messages
            result.append(
                ToolMessage(
                    content=str(observation),
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": result}

    # ── Step4：定义条件边函数 ─────────────────────────────
    # 文档写法：返回类型用 Literal 注解，列出所有可能的下一个节点
    def should_continue(state: NoteAgentState) -> Literal["tool_node", END]:
        """Decide if we should continue the loop or stop"""
        messages = state["messages"]
        last_message = messages[-1]
        # 如果 LLM 决定调工具 → 去 tool_node
        if last_message.tool_calls:
            return "tool_node"
        # 否则结束
        return END

    # ── Step5：组装图 ─────────────────────────────────────
    # 文档写法：StateGraph → add_node → add_edge → compile
    agent_builder = StateGraph(NoteAgentState)

    # 添加节点（文档命名：llm_call 和 tool_node）
    agent_builder.add_node("llm_call", llm_call)
    agent_builder.add_node(
        "tool_node",
        tool_node,
        # Data step 加重试策略（文档 thinking-in-langgraph 里提到）
        retry_policy=RetryPolicy(max_attempts=3, initial_interval=1.0),
    )

    # 添加边
    # 文档写法：固定边直接 add_edge
    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_edge("tool_node", "llm_call")  # 工具完成 → 回 llm_call

    # 文档写法：条件边第三个参数传列表，不传字典
    # ["tool_node", END] 就是 should_continue 可能返回的所有值
    agent_builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["tool_node", END],   # ← 文档新写法，列表而不是字典
    )

    # 编译，传入 checkpointer 实现持久化
    return agent_builder.compile(checkpointer=_checkpointer)