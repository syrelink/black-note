"""GameRover 的 LangGraph Harness。

一轮请求的主路径：
START → TurnContext → ContextCompaction → Agent
→（可选 ToolExecution → ProcessToolResults → ContextCompaction → Agent）→ END。

当前轮图片已经位于 HumanMessage 的多模态内容中，主模型会直接读取原图；
只有图片所在旧轮次被压缩时，memory.py 才生成 VisualMemory 并写入 RunningSummary。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.game_agent.image_memory import ImageMemoryService
from app.game_agent.memory import (
    ContextBudget,
    ContextManager,
    calibrate_token_ledger,
    message_tokens,
    sync_token_ledger,
)
from app.game_agent.models import (
    ContextMetrics,
    HarnessState,
    RunningSummary,
    ToolTrace,
    TurnTokenUsage,
)
from app.game_agent.prompts import FORCE_FINISH_PROMPT, build_agent_system_prompt
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


def close_tool_calls_for_force_finish(message: AIMessage) -> tuple[list[ToolMessage], list[ToolTrace]]:
    """为未执行的 Tool Call 补齐 ToolMessage，保持消息协议合法。"""
    tool_messages = []
    traces = []
    for call in message.tool_calls:
        name = call.get("name", "unknown")
        content = json.dumps({
            "error": "tool call skipped because the per-turn tool round limit was reached",
            "tool": name,
        }, ensure_ascii=False)
        tool_messages.append(ToolMessage(
            content=content,
            tool_call_id=call.get("id", name),
            name=name,
            id=str(uuid4()),
        ))
        traces.append(ToolTrace(
            name=name,
            arguments=call.get("args", {}),
            status="error",
            preview=content,
            latency_ms=0,
        ))
    return tool_messages, traces


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


def build_game_assistant(checkpointer) -> GameAgentHarness:
    """组装节点依赖、定义节点函数并编译 LangGraph。"""
    # MiMo 同时负责文字、当前轮原图、工具选择、Query 规划和历史图片摘要。
    model = create_model()
    tools = AGENT_TOOLS
    configure_search_planner(model)
    budget = ContextBudget.from_env()
    image_memory_service = ImageMemoryService(model)
    context_manager = ContextManager(model, budget, image_service=image_memory_service)
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
    max_tool_rounds = int(os.getenv("GAME_MAX_TOOL_ROUNDS", "3"))
    agent_system_prompt = build_agent_system_prompt(skill_registry.catalog_prompt())

    def skill_system_messages(state: HarnessState) -> list[SystemMessage]:
        """仅为当前一轮临时注入已激活 Skill，避免正文进入持久 messages。"""
        documents = []
        for name in state.get("active_skills", []):
            documents.append(skill_registry.load(name))
        for key in state.get("loaded_skill_resources", []):
            name, resource = skill_registry.split_resource_key(key)
            documents.append(skill_registry.load(name, resource))
        return [SystemMessage(content=(
            "【已加载的受信任 Skill 指令】\n"
            f"Skill: {document.name}\n"
            f"Resource: {document.resource or 'SKILL.md'}\n\n"
            f"{document.content}"
        )) for document in documents]

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
        """创建本轮 TurnContext：重置临时状态并同步新增消息的 Token 记录。"""
        summary = RunningSummary.model_validate(state.get("running_summary", {}))
        ledger = sync_token_ledger(
            state.get("messages", []), state.get("token_ledger"), summary
        )
        return {
            "tool_trace": [],
            "active_skills": [],
            "loaded_skill_resources": [],
            "skill_trace": [],
            "tool_rounds": 0,
            "turn_count": state.get("turn_count", 0) + 1,
            "compacted": False,
            "compaction_events": [],
            "token_ledger": ledger.model_dump(),
            "turn_token_usage": TurnTokenUsage().model_dump(),
        }

    async def run_context_compaction(state: HarnessState):
        """在每次模型调用前检查压力，并流式发布压缩生命周期事件。"""
        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = lambda _: None
        return await context_manager.compact(
            state,
            emit=lambda event: writer({"kind": "harness_event", "event": event}),
            node="ContextCompaction",
        )

    async def call_agent(state: HarnessState):
        """组装 System、Summary 和近期多模态消息，让模型回答或请求工具。"""
        model_context = context_manager.build_model_context(
            state,
            agent_system_prompt,
            skill_system_messages(state),
        )
        # 模型返回普通文本时结束；返回 tool_calls 时由条件边进入 ToolExecution。
        response = await stream_model(model_with_tools, model_context, "Agent")
        if not response.id:
            response.id = str(uuid4())
        summary = RunningSummary.model_validate(state.get("running_summary", {}))
        ledger = sync_token_ledger(
            [*state.get("messages", []), response],
            state.get("token_ledger"),
            summary,
        )
        estimated_prompt_tokens = message_tokens(model_context)
        usage = getattr(response, "usage_metadata", None) or {}
        actual_prompt_tokens = usage.get("input_tokens")
        ledger = calibrate_token_ledger(
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
        return {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
            "context_metrics": metrics.model_dump(),
            "token_ledger": ledger.model_dump(),
            "turn_token_usage": token_usage.model_dump(),
        }

    def route_after_agent(state: HarnessState) -> Literal["ToolExecution", "ForceFinish", "end"]:
        """根据最后一条 AIMessage 决定结束、执行工具或强制收敛。"""
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        if state.get("tool_rounds", 0) >= max_tool_rounds:
            return "ForceFinish"
        return "ToolExecution"

    async def process_tool_results(state: HarnessState):
        """解析 ToolNode 结果，并登记 Skill、工具轨迹、轮次和 Token 账本。"""
        tool_messages = []
        for message in reversed(state.get("messages", [])):
            if isinstance(message, ToolMessage):
                tool_messages.append(message)
                continue
            break
        tool_messages.reverse()
        traces = [
            ToolTrace.model_validate(message.artifact["harness_trace"])
            for message in tool_messages
            if isinstance(message.artifact, dict) and message.artifact.get("harness_trace")
        ]
        existing_trace = [ToolTrace.model_validate(item) for item in state.get("tool_trace", [])]
        active_skills = list(state.get("active_skills", []))
        loaded_resources = list(state.get("loaded_skill_resources", []))
        skill_trace = list(state.get("skill_trace", []))
        for trace in traces:
            if trace.name != "load_skill" or trace.status != "success":
                continue
            name = str(trace.arguments.get("name", "")).strip()
            resource = trace.arguments.get("resource")
            if name and name not in active_skills:
                active_skills.append(name)
            if name and resource:
                key = skill_registry.resource_key(name, str(resource).strip())
                if key not in loaded_resources:
                    loaded_resources.append(key)
            skill_trace.append({"name": name, "resource": resource or None})
        summary = RunningSummary.model_validate(state.get("running_summary", {}))
        ledger = sync_token_ledger(
            state.get("messages", []),
            state.get("token_ledger"),
            summary,
        )
        return {
            "tool_trace": [trace.model_dump() for trace in [*existing_trace, *traces]],
            "active_skills": active_skills,
            "loaded_skill_resources": loaded_resources,
            "skill_trace": skill_trace,
            "tool_rounds": state.get("tool_rounds", 0) + 1,
            "token_ledger": ledger.model_dump(),
        }

    async def force_finish(state: HarnessState):
        """达到工具轮次上限后先整理上下文，再仅用已有证据生成最终回答。"""
        try:
            writer = get_stream_writer()
        except RuntimeError:
            writer = lambda _: None
        compaction_update = await context_manager.compact(
            state,
            emit=lambda event: writer({"kind": "harness_event", "event": event}),
            node="ForceFinish",
        )
        compacted_state = {**state, **compaction_update}
        if compaction_update.get("messages"):
            compacted_state["messages"] = add_messages(
                state.get("messages", []),
                compaction_update["messages"],
            )
        last = compacted_state["messages"][-1]
        closing_messages, skipped_traces = close_tool_calls_for_force_finish(last)
        model_context = context_manager.build_model_context(
            compacted_state,
            agent_system_prompt,
            [*skill_system_messages(compacted_state), SystemMessage(content=FORCE_FINISH_PROMPT)],
        )
        model_context.extend(closing_messages)
        response = await stream_model(model, model_context, "ForceFinish")
        final_message = AIMessage(content=response.content, id=str(uuid4()))
        summary = RunningSummary.model_validate(compacted_state.get("running_summary", {}))
        ledger = sync_token_ledger(
            [*compacted_state.get("messages", []), *closing_messages, final_message],
            compacted_state.get("token_ledger"),
            summary,
        )
        estimated_prompt_tokens = message_tokens(model_context)
        usage = getattr(response, "usage_metadata", None) or {}
        actual_prompt_tokens = usage.get("input_tokens")
        ledger = calibrate_token_ledger(
            ledger.model_dump(), estimated_prompt_tokens, actual_prompt_tokens
        )
        metrics = ContextMetrics.model_validate(compacted_state.get("context_metrics", {})).model_copy(
            update={
                "active_message_tokens": ledger.active_message_tokens,
                "summary_tokens": ledger.summary_tokens,
                "model_input_tokens": actual_prompt_tokens or (
                    estimated_prompt_tokens + ledger.protocol_overhead_tokens
                ),
                "model_input_source": "api_usage" if actual_prompt_tokens else "estimated",
            }
        )
        token_usage = accumulate_token_usage(compacted_state, response, model_context)
        existing_trace = [ToolTrace.model_validate(item) for item in compacted_state.get("tool_trace", [])]
        return {
            **compaction_update,
            "messages": [
                *compaction_update.get("messages", []),
                *closing_messages,
                final_message,
            ],
            "tool_trace": [trace.model_dump() for trace in [*existing_trace, *skipped_traces]],
            "llm_calls": compacted_state.get("llm_calls", 0) + 1,
            "token_ledger": ledger.model_dump(),
            "context_metrics": metrics.model_dump(),
            "turn_token_usage": token_usage.model_dump(),
        }

    # 第一部分：注册节点。节点只返回 State 增量，LangGraph 负责合并。
    builder = StateGraph(HarnessState)
    builder.add_node("TurnContext", build_turn_context)
    builder.add_node("ContextCompaction", run_context_compaction)
    builder.add_node("Agent", call_agent)
    builder.add_node("ToolExecution", tool_node)
    builder.add_node("ProcessToolResults", process_tool_results)
    builder.add_node("ForceFinish", force_finish)
    # 第二部分：连接固定边和条件边，明确一轮请求所有可能的执行路径。
    builder.add_edge(START, "TurnContext")
    builder.add_edge("TurnContext", "ContextCompaction")
    builder.add_edge("ContextCompaction", "Agent")
    builder.add_conditional_edges(
        "Agent",
        route_after_agent,
        {
            "ToolExecution": "ToolExecution",
            "ForceFinish": "ForceFinish",
            "end": END,
        },
    )
    # ToolNode 写回 ToolMessage；随后更新业务状态，再让模型基于证据继续推理。
    builder.add_edge("ToolExecution", "ProcessToolResults")
    builder.add_edge("ProcessToolResults", "ContextCompaction")
    builder.add_edge("ForceFinish", END)

    # checkpointer 让同一个 thread_id 可以跨请求、跨服务重启恢复 State。
    return GameAgentHarness(
        graph=builder.compile(checkpointer=checkpointer),
        context_manager=context_manager,
        skill_registry=skill_registry,
    )
