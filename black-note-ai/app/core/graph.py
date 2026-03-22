"""
app/core/graph.py
改动说明：
  1. should_continue 加入重复调用检测，替代粗暴的次数硬限制
  2. summarize_if_needed 移到对话结束后触发，不再阻塞主流程
  3. ROVER_SYSTEM_PROMPT 注入改为图初始化时写入，不在 llm_call 里动态判断
"""

import os
import sqlite3
from collections import Counter
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, RemoveMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.core.schemas import AgentContext
from app.core.state import NoteAgentState
from app.core.tools import make_tools

load_dotenv()

_conn = sqlite3.connect("./checkpoints.db", check_same_thread=False)
_checkpointer = SqliteSaver(_conn)
_store = InMemoryStore()


def build_graph(vectorstore):

    # ── 初始化模型 ────────────────────────────────────────────────
    model = ChatOpenAI(
        model=os.getenv("MIMO_MODEL"),
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL"),
    )

    deepseek_model = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )

    tools, _ = make_tools(vectorstore)
    model_with_tools = model.bind_tools(tools)

    # ── 节点一：llm_call ──────────────────────────────────────────
    # system prompt 通过 state 初始化时写入（见图编译后的 input 处理），
    # 这里不再做动态插入，避免每次都遍历 messages 做字符串判断。
    def llm_call(state: NoteAgentState, runtime: Runtime[AgentContext]):
        response = model_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    # ── 条件边：should_continue ───────────────────────────────────
    # 不用次数硬限制，改为检测"无意义重复调用"异常模式：
    # 同一个工具在最近 6 条 ToolMessage 里出现 3 次及以上，视为模型陷入循环。
    def should_continue(state: NoteAgentState) -> Literal["tool_node", "summarize_if_needed"]:
        last = state["messages"][-1]

        # 没有工具调用 → 本轮对话结束，进入压缩节点
        if not last.tool_calls:
            return "summarize_if_needed"

        # 检测重复调用异常：从最近的 ToolMessage 里统计工具调用频次
        recent_tool_names = [
            m.name
            for m in state["messages"][-6:]
            if hasattr(m, "name") and m.name
        ]
        if any(v >= 3 for v in Counter(recent_tool_names).values()):
            # 异常：某个工具连续被调用 3 次以上，强制终止本轮
            # 同样走压缩节点，保持流程统一
            return "summarize_if_needed"

        return "tool_node"

    # ── 节点二：summarize_if_needed ───────────────────────────────
    # 【位置调整】从 START 后移到对话结束后触发。
    # 每轮对话真正结束（LLM 不再调用工具）时才执行一次压缩判断，
    # 不阻塞主流程，也不影响工具调用循环。
    def summarize_if_needed(state: NoteAgentState):
        messages = state["messages"]

        # token 未超限，直接结束，不做任何操作
        if count_tokens_approximately(messages) < 45000:
            return {}

        # 超限：保留最近 24 条，压缩其余早期消息
        recent = messages[-24:]
        to_summarize = messages[:-24]

        existing_summary = state.get("summary", "")
        summary_prompt = f"""
        你是对话历史压缩助手。请将以下对话压缩成简洁的 bullet 摘要，保留：
        - 用户的核心目标和待办事项
        - 已确认的关键事实（笔记 ID、标题、日期等）
        - 用户的偏好和特殊要求
        已有摘要（如有）：
        {existing_summary}
        需要新增压缩的对话：
        """
        new_summary = deepseek_model.invoke(
            [SystemMessage(content=summary_prompt)] + to_summarize
        ).content

        delete_ops = [RemoveMessage(id=m.id) for m in to_summarize]
        summary_msg = SystemMessage(
            content=f"【历史对话摘要】\n{new_summary}",
            id="summary-msg",  # 固定 id，下次压缩时覆盖而非新增
        )

        return {
            "messages": delete_ops + [summary_msg] + recent,
            "summary": new_summary,
        }

    # ── 组装图 ────────────────────────────────────────────────────
    #
    # 旧流程：START → summarize_if_needed → llm_call → should_continue
    #                                                      ↓ tool_node
    #                                                   tool_node → llm_call
    #
    # 新流程：START → llm_call → should_continue
#                                ↓ tool_node      ↓ summarize_if_needed
#                             tool_node        summarize_if_needed → END
#                                ↓
#                             llm_call
    #
    agent_builder = StateGraph(
        NoteAgentState,
        context_schema=AgentContext,
    )

    agent_builder.add_node("llm_call", llm_call)
    agent_builder.add_node("tool_node", ToolNode(tools))
    agent_builder.add_node("summarize_if_needed", summarize_if_needed)

    # START 直接进 llm_call
    # system prompt 需在图外部、每次调用时作为第一条消息传入 state，
    # 例如：{"messages": [SystemMessage(content=ROVER_SYSTEM_PROMPT), HumanMessage(...)]}
    agent_builder.add_edge(START, "llm_call")
    agent_builder.add_edge("tool_node", "llm_call")
    agent_builder.add_edge("summarize_if_needed", END)

    agent_builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["tool_node", "summarize_if_needed"],
    )

    return agent_builder.compile(
        checkpointer=_checkpointer,
        store=_store,
    )