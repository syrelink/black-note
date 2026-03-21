"""
app/core/graph.py
实现：最近 N 条 + 总结式历史
"""

import os
import sqlite3
from typing import Literal

from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, RemoveMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore
from langgraph.prebuilt import ToolNode
from langgraph.types import RetryPolicy
from langchain_core.messages.utils import count_tokens_approximately

from app.core.state import NoteAgentState
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.core.tools import make_tools
from app.core.schemas import AgentContext
from langgraph.runtime import Runtime

load_dotenv()

# ── 持久化（全局单例）────────────────────────────────────────
_conn = sqlite3.connect("./checkpoints.db", check_same_thread=False)
_checkpointer = SqliteSaver(_conn)
_store = InMemoryStore()


def build_graph(vectorstore):

    # ── 初始化模型 ───────────────────────────────────────────────
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

    # ── 节点一：summarize_if_needed ──────────────────────────────
    # 职责：检查 token 是否超限，超了就压缩历史，更新 state
    def summarize_if_needed(state: NoteAgentState):
        messages = state["messages"]

        # token 未超限，直接跳过（返回空 dict 表示不修改 state）
        if count_tokens_approximately(messages) < 45000:
            return {}

        # ── 超限：把除最近 24 条以外的消息压缩成摘要 ──
        recent       = messages[-24:]   # 最近 12 轮（每轮 user+ai = 2 条）
        to_summarize = messages[:-24]   # 需要压缩的早期消息

        # 用 deepseek 生成摘要（便宜，省 token）
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

        # 用 RemoveMessage 删除早期消息，再插入摘要消息
        # RemoveMessage 是 LangGraph 官方删除消息的方式
        delete_ops = [RemoveMessage(id=m.id) for m in to_summarize]

        summary_msg = SystemMessage(
            content=f"【历史对话摘要】\n{new_summary}",
            id="summary-msg",   # 固定 id，下次压缩时覆盖
        )

        return {
            "messages": delete_ops + [summary_msg] + recent,
            "summary": new_summary,
        }

    # ── 节点二：llm_call ─────────────────────────────────────────
    def llm_call(state: NoteAgentState, runtime: Runtime[AgentContext]):
        messages = state["messages"]

        # 确保 system prompt 只在最前面出现一次
        if not any(isinstance(m, SystemMessage) and "ROVER" in (m.content or "") for m in messages):
            messages = [SystemMessage(content=ROVER_SYSTEM_PROMPT)] + messages

        response = model_with_tools.invoke(messages)

        return {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    # ── 条件边 ───────────────────────────────────────────────────
    def should_continue(state: NoteAgentState) -> Literal["tool_node", "__end__"]:
        last = state["messages"][-1]
        if last.tool_calls:
            return "tool_node"
        return "__end__"

    # ── 组装图 ────────────────────────────────────────────────────
    agent_builder = StateGraph(
        NoteAgentState,
        context_schema=AgentContext,
    )

    agent_builder.add_node("summarize_if_needed", summarize_if_needed)
    agent_builder.add_node("llm_call",  llm_call)
    agent_builder.add_node("tool_node", ToolNode(tools))

    # 每次进入图，先过 summarize_if_needed，再到 llm_call
    agent_builder.add_edge(START,               "summarize_if_needed")
    agent_builder.add_edge("summarize_if_needed", "llm_call")
    agent_builder.add_edge("tool_node",          "llm_call")

    agent_builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["tool_node", "__end__"],
    )

    return agent_builder.compile(
        checkpointer=_checkpointer,
        store=_store,
    )