"""GameRover 的 LangGraph Harness。

一轮请求的主路径：
START → TurnContext → ContextCompaction → Agent
→（可选 ToolExecution → ContextCompaction → Agent）→ END。

当前轮图片已经位于 HumanMessage 的多模态内容中，主模型会直接读取原图；
图片所在旧轮次被压缩时，原图与同轮文字一起进入摘要模型并写入 ContextSummary。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.game_agent.attachments import AttachmentLoader, hydrate_current_images
from app.game_agent.memory import (
    ContextBudget,
    ContextManager,
    context_summary_from_state,
    message_tokens,
    record_token_observation,
    sync_token_ledger,
)
from app.game_agent.models import (
    ContextMetrics,
    HarnessState,
    ToolTrace,
    TurnTokenUsage,
)
from app.game_agent.prompts import build_agent_system_prompt
from app.game_agent.skills import SkillRegistry
from app.game_agent.tools import AGENT_TOOLS, configure_search_planner, skill_registry
from app.game_agent.tracing import create_tool_call_wrapper


def create_model(prefix: str = "GAME_ASSISTANT") -> ChatOpenAI:
    """按前缀读取环境变量，创建普通模型或视觉模型。"""
    return ChatOpenAI(
        model=os.getenv(f"{prefix}_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv(f"{prefix}_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv(f"{prefix}_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.2,
    )


@dataclass
class GameAgentHarness:
    """向 FastAPI 暴露编译后的图和上下文管理器。"""
    graph: object
    context_manager: ContextManager
    skill_registry: SkillRegistry

    async def force_compact(self, session_id: str) -> dict:
        """供管理接口主动压缩指定会话，不需要重新执行完整 Agent 图。"""
        config = {"configurable": {"thread_id": session_id}}
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values:
            return {"compacted": False, "reason": "session not found"}
        update = await self.context_manager.compact(snapshot.values, force=True)
        await self.graph.aupdate_state(config, update, as_node="ContextCompaction")
        return update


def build_game_assistant(
    checkpointer,
    attachment_loader: AttachmentLoader | None = None,
) -> GameAgentHarness:
    """组装节点依赖、定义节点函数并编译 LangGraph。"""
    # MiMo 同时负责文字、图片、工具选择、Query 规划和统一上下文摘要。
    model = create_model()
    tools = AGENT_TOOLS
    configure_search_planner(model)
    budget = ContextBudget.from_env()
    context_manager = ContextManager(model, budget)
    tool_node = ToolNode(
        tools,
        handle_tool_errors=True,
        awrap_tool_call=create_tool_call_wrapper(
            result_token_budget=budget.tool_result_tokens,
            default_timeout_seconds=float(os.getenv("GAME_TOOL_TIMEOUT_SECONDS", "35")),
            tool_timeouts={
                "web_search": float(os.getenv("GAME_WEB_SEARCH_TIMEOUT_SECONDS", "45"))
            },
        ),
    )
    # bind_tools 只把 Schema 告诉模型；官方 ToolNode 负责并发执行和协议闭合。
    model_with_tools = model.bind_tools(tools)
    agent_system_prompt = build_agent_system_prompt(skill_registry.catalog_prompt())

    async def stream_model(runnable, model_context, node: str):
        """流式调用模型，并发布请求、首字和完成三个可观测事件。"""
        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = lambda _: None
        started = time.perf_counter()
        first_token_at = None
        output_chunks = 0
        estimated_input_tokens = message_tokens(model_context)
        writer({"kind": "harness_event", "event": {
            "event_type": "model/start",
            "component": "model",
            "node": node,
            "status": "running",
            "model_name": getattr(runnable, "model_name", None) or getattr(runnable, "model", None),
            "estimated_input_tokens": estimated_input_tokens,
        }})
        response = None
        try:
            async for chunk in runnable.astream(model_context):
                response = chunk if response is None else response + chunk
                if isinstance(chunk.content, str) and chunk.content:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        writer({"kind": "harness_event", "event": {
                            "event_type": "model/first_token",
                            "component": "model",
                            "node": node,
                            "status": "streaming",
                            "ttft_ms": int((first_token_at - started) * 1000),
                        }})
                    output_chunks += 1
                    writer({"kind": "model_token", "node": node, "content": chunk.content})
        except Exception as exc:
            writer({"kind": "harness_event", "event": {
                "event_type": "model/error",
                "component": "model",
                "node": node,
                "status": "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "ttft_ms": int((first_token_at - started) * 1000) if first_token_at else None,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
            }})
            raise
        finished = time.perf_counter()
        response = response or AIMessage(content="")
        usage = getattr(response, "usage_metadata", None) or {}
        output_tokens = int(usage.get("output_tokens") or message_tokens([response]))
        generation_ms = int((finished - (first_token_at or started)) * 1000)
        writer({"kind": "harness_event", "event": {
            "event_type": "model/end",
            "component": "model",
            "node": node,
            "status": "success",
            "duration_ms": int((finished - started) * 1000),
            "ttft_ms": int((first_token_at - started) * 1000) if first_token_at else None,
            "generation_ms": generation_ms,
            "input_tokens": int(usage.get("input_tokens") or estimated_input_tokens),
            "estimated_input_tokens": estimated_input_tokens,
            "provider_input_tokens": int(usage["input_tokens"]) if usage.get("input_tokens") else None,
            "output_tokens": output_tokens,
            "tokens_per_second": round(output_tokens / (generation_ms / 1000), 2) if generation_ms else None,
            "output_chunks": output_chunks,
            "requested_tools": [call.get("name", "unknown") for call in response.tool_calls],
        }})
        return response

    def accumulate_token_usage(
        state: HarnessState,
        response: AIMessage,
        model_context: list,
    ) -> TurnTokenUsage:
        """优先累计 API 实测 Token；供应商不返回 usage 时退化为本地估算。"""
        current = TurnTokenUsage.model_validate(state.get("turn_token_usage", {}))
        usage = getattr(response, "usage_metadata", None) or {}
        estimated_input = message_tokens(model_context)
        estimated_output = message_tokens([response])
        input_tokens = int(usage.get("input_tokens") or estimated_input)
        output_tokens = int(usage.get("output_tokens") or estimated_output)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        return current.model_copy(update={
            "input_tokens": current.input_tokens + input_tokens,
            "output_tokens": current.output_tokens + output_tokens,
            "total_tokens": current.total_tokens + total_tokens,
            "model_calls": current.model_calls + 1,
            "estimated_calls": current.estimated_calls + (0 if usage.get("input_tokens") else 1),
        })

    def build_turn_context(state: HarnessState):
        """创建本轮 TurnContext：重置本轮审计状态并同步 Token 估算缓存。"""
        summary = context_summary_from_state(state)
        ledger = sync_token_ledger(
            state.get("messages", []), state.get("token_ledger"), summary
        )
        return {
            "tool_trace": [],
            "skill_trace": [],
            "tool_rounds": 0,
            "turn_count": state.get("turn_count", 0) + 1,
            "compacted": False,
            "compaction_events": [],
            "token_ledger": ledger.model_dump(),
            "turn_token_usage": TurnTokenUsage().model_dump(),
        }

    def publish_harness_event(event: dict) -> None:
        """图以流式模式运行时发布审计事件；普通调用和测试中静默跳过。"""
        try:
            writer = get_stream_writer()
        except RuntimeError:
            return
        writer({"kind": "harness_event", "event": event})

    async def run_context_compaction(state: HarnessState):
        """检查当前上下文压力，并返回无需压缩或完成压缩后的 State 增量。"""
        return await context_manager.compact(
            state,
            emit=publish_harness_event,
            node="ContextCompaction",
        )

    async def call_agent(state: HarnessState, config: RunnableConfig):
        """组装持久文本上下文，并只为本次请求临时还原当前 Turn 的图片。"""
        model_context = context_manager.build_model_context(
            state,
            agent_system_prompt,
        )
        session_id = str(config.get("configurable", {}).get("thread_id", ""))
        model_context = await hydrate_current_images(
            model_context,
            state.get("current_attachments", []),
            session_id=session_id,
            loader=attachment_loader,
        )
        # 模型返回普通文本时结束；返回 tool_calls 时由条件边进入 ToolExecution。
        response = await stream_model(model_with_tools, model_context, "Agent")
        if not response.id:
            response.id = str(uuid4())
        summary = context_summary_from_state(state)
        ledger = sync_token_ledger(
            [*state.get("messages", []), response],
            state.get("token_ledger"),
            summary,
        )
        estimated_prompt_tokens = message_tokens(model_context)
        usage = getattr(response, "usage_metadata", None) or {}
        actual_prompt_tokens = usage.get("input_tokens")
        ledger = record_token_observation(
            ledger.model_dump(), estimated_prompt_tokens, actual_prompt_tokens
        )
        metrics = ContextMetrics.model_validate(state.get("context_metrics", {})).model_copy(
            update={
                "active_message_tokens": ledger.active_message_tokens,
                "summary_tokens": ledger.summary_tokens,
                "model_input_tokens": actual_prompt_tokens or (
                    estimated_prompt_tokens + ledger.protocol_overhead_tokens
                ),
                "model_input_source": "api_usage" if actual_prompt_tokens else "estimated",
            }
        )
        token_usage = accumulate_token_usage(state, response, model_context)
        attachment_artifacts = dict(state.get("attachment_artifacts", {}))
        response_text = response.content if isinstance(response.content, str) else json.dumps(
            response.content, ensure_ascii=False, default=str
        )
        for item in state.get("current_attachments", []):
            attachment_id = str(item.get("attachment_id", ""))
            if not attachment_id:
                continue
            attachment_artifacts[attachment_id] = {
                "artifact_id": attachment_id,
                "kind": "image_reference",
                "name": item.get("name"),
                "mime_type": item.get("mime_type"),
                "size": item.get("size", 0),
                "summary": response_text[:1600],
            }
        return {
            "messages": [response],
            "attachment_artifacts": attachment_artifacts,
            "llm_calls": state.get("llm_calls", 0) + 1,
            "context_metrics": metrics.model_dump(),
            "token_ledger": ledger.model_dump(),
            "turn_token_usage": token_usage.model_dump(),
        }

    def route_after_agent(state: HarnessState) -> Literal["ToolExecution", "end"]:
        """模型请求工具时继续循环，否则结束当前 Turn。"""
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        return "ToolExecution"

    async def execute_tools(state: HarnessState):
        """执行本批工具，并在同一节点完成 ToolMessage、轨迹和 Skill 审计。"""
        tool_update = await tool_node.ainvoke(state)
        tool_messages = [
            message for message in tool_update.get("messages", [])
            if isinstance(message, ToolMessage)
        ]
        traces = [
            ToolTrace.model_validate(message.artifact["harness_trace"])
            for message in tool_messages
            if isinstance(message.artifact, dict) and message.artifact.get("harness_trace")
        ]
        existing_trace = [ToolTrace.model_validate(item) for item in state.get("tool_trace", [])]
        skill_trace = list(state.get("skill_trace", []))
        for trace in traces:
            if trace.name not in {"skill", "read_skill_reference"} or trace.status != "success":
                continue
            name = str(trace.arguments.get("name", "")).strip()
            resource = trace.arguments.get("path")
            skill_trace.append({
                "name": name,
                "resource": resource or None,
                "tool": trace.name,
            })
        summary = context_summary_from_state(state)
        ledger = sync_token_ledger(
            [*state.get("messages", []), *tool_messages],
            state.get("token_ledger"),
            summary,
        )
        return {
            "messages": tool_messages,
            "tool_trace": [trace.model_dump() for trace in [*existing_trace, *traces]],
            "skill_trace": skill_trace,
            "tool_rounds": state.get("tool_rounds", 0) + 1,
            "token_ledger": ledger.model_dump(),
        }

    # 第一部分：注册节点。节点只返回 State 增量，LangGraph 负责合并。
    builder = StateGraph(HarnessState)
    builder.add_node("TurnContext", build_turn_context)
    builder.add_node("ContextCompaction", run_context_compaction)
    builder.add_node("Agent", call_agent)
    builder.add_node("ToolExecution", execute_tools)
    # 第二部分：连接固定边和条件边，明确一轮请求所有可能的执行路径。
    builder.add_edge(START, "TurnContext")
    builder.add_edge("TurnContext", "ContextCompaction")
    builder.add_edge("ContextCompaction", "Agent")
    builder.add_conditional_edges(
        "Agent",
        route_after_agent,
        {
            "ToolExecution": "ToolExecution",
            "end": END,
        },
    )
    # 工具节点同时写回 ToolMessage 与审计信息，再测压并继续 Agent 循环。
    builder.add_edge("ToolExecution", "ContextCompaction")

    # checkpointer 让同一个 thread_id 可以跨请求、跨服务重启恢复 State。
    return GameAgentHarness(
        graph=builder.compile(checkpointer=checkpointer),
        context_manager=context_manager,
        skill_registry=skill_registry,
    )
