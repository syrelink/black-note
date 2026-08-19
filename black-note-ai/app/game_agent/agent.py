"""GameRover 的无 LangGraph Agent 循环。

一轮请求的主路径是显式的 while 循环：

    TurnContext → ContextCompaction → Agent
    →（可选 ToolExecution → ContextCompaction → Agent）→ END。

与 LangGraph 版的区别：没有 StateGraph / Checkpointer / ToolNode。
State 是普通 dict，会话状态由 SessionStore 持久化，工具由本模块手动执行。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Awaitable, Callable
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI

from app.game_agent.attachments import AttachmentLoader, hydrate_current_images
from app.game_agent.memory import (
    ContextBudget,
    ContextManager,
    context_summary_from_state,
    message_tokens,
    record_token_observation,
    sync_token_ledger,
)
from app.game_agent.models import ContextMetrics, ToolTrace, TurnTokenUsage
from app.game_agent.prompts import build_agent_system_prompt
from app.game_agent.skills import SkillRegistry
from app.game_agent.tools import AGENT_TOOLS, skill_registry
from app.game_agent.tracing import truncate_tool_payload


EmitFn = Callable[[dict], Awaitable[None]]


def create_model(prefix: str = "GAME_ASSISTANT") -> ChatOpenAI:
    """按前缀读取环境变量，创建模型客户端。"""
    return ChatOpenAI(
        model=os.getenv(f"{prefix}_MODEL") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv(f"{prefix}_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv(f"{prefix}_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.2,
    )


class GameAgent:
    """单 Agent Harness：普通 dict 状态 + while 循环 + 手动工具执行。"""

    def __init__(
        self,
        model: BaseChatModel,
        tools: list,
        context_manager: ContextManager,
        skill_registry: SkillRegistry,
        session_store,
        attachment_loader: AttachmentLoader | None = None,
    ):
        self.model = model
        self.tools = {tool.name: tool for tool in tools}
        self.model_with_tools = model.bind_tools(tools)
        self.context_manager = context_manager
        self.budget = context_manager.budget
        self.skill_registry = skill_registry
        self.session_store = session_store
        self.attachment_loader = attachment_loader
        self.agent_system_prompt = build_agent_system_prompt(skill_registry.catalog_prompt())
        self.default_timeout = float(os.getenv("GAME_TOOL_TIMEOUT_SECONDS", "35"))

    # ---------- 会话状态 ----------
    async def load_state(self, session_id: str) -> dict:
        return await self.session_store.load_state(session_id)

    async def save_state(self, session_id: str, state: dict) -> None:
        await self.session_store.save_state(session_id, state)

    async def force_compact(self, session_id: str) -> dict:
        """供管理接口主动压缩指定会话，不需要重新执行完整 Agent 循环。"""
        state = await self.load_state(session_id)
        if not state.get("messages"):
            return {"compacted": False, "reason": "session not found"}
        update = await self.context_manager.compact(state, force=True)
        messages = update.pop("messages", None)
        if messages is not None:
            state["messages"] = messages
        state.update(update)
        await self.save_state(session_id, state)
        return update

    # ---------- 一轮主循环 ----------
    async def run_turn(
        self,
        session_id: str,
        user_message,
        current_attachments: list,
        force_compaction: bool = False,
        emit: EmitFn | None = None,
    ) -> dict:
        async def _emit(event: dict) -> None:
            if emit is not None:
                await emit(event)

        state = await self.load_state(session_id)

        # TurnContext：追加用户消息、重置本轮临时字段（临时字段不持久化）。
        state["messages"] = list(state.get("messages", [])) + [user_message]
        state["current_attachments"] = list(current_attachments)
        state["turn_count"] = int(state.get("turn_count", 0)) + 1
        started = time.perf_counter()
        await _emit({"kind": "harness_event", "event": {
            "event_type": "node", "node": "TurnContext",
            "edge": "START → TurnContext", "turn_count": state["turn_count"],
        }})

        turn_token_usage = TurnTokenUsage()
        tool_trace: list[dict] = []
        skill_trace: list[dict] = []
        tool_rounds = 0
        compacted = False
        context_metrics: dict = {}
        last_response = AIMessage(content="")

        while True:
            # ContextCompaction：每次调用模型前测压，超阈值才压缩。
            compaction_events: list[dict] = []
            update = await self.context_manager.compact(
                state,
                force=bool(force_compaction) and tool_rounds == 0,
                emit=compaction_events.append,
                node="ContextCompaction",
            )
            messages = update.pop("messages", None)
            if messages is not None:
                state["messages"] = messages
            state.update(update)
            compacted = compacted or bool(update.get("compacted", False))
            for event in compaction_events:
                await _emit({"kind": "harness_event", "event": event})

            # Agent：调模型（流式），返回 AIMessage 与 usage。
            response, usage = await self._call_model(state, session_id, _emit)
            last_response = response
            state["messages"] = list(state["messages"]) + [response]
            turn_token_usage = self._accumulate(turn_token_usage, usage, response)
            context_metrics = self._build_context_metrics(state, usage)
            await _emit({"kind": "harness_event", "event": {
                "event_type": "node", "node": "Agent",
                "edge": "ContextCompaction → Agent",
                "tool_calls": [c.get("name", "unknown") for c in response.tool_calls],
            }})

            if not response.tool_calls:
                break

            # ToolExecution：手动执行本批工具。
            tool_messages, traces = await self._execute_tools(state, response, _emit)
            state["messages"] = list(state["messages"]) + tool_messages
            tool_trace.extend([t.model_dump() for t in traces])
            tool_rounds += 1
            await _emit({"kind": "harness_event", "event": {
                "event_type": "node", "node": "ToolExecution",
                "edge": "Agent → ToolExecution", "tool_count": len(traces),
            }})

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        state["context_metrics"] = context_metrics
        await self.save_state(session_id, state)
        await _emit({"kind": "harness_event", "event": {
            "event_type": "node", "node": "END",
            "edge": "Agent → END", "elapsed_ms": elapsed_ms,
        }})

        return {
            "answer": self._answer_text(last_response),
            "tool_trace": tool_trace,
            "skill_trace": skill_trace,
            "context_metrics": context_metrics,
            "token_usage": turn_token_usage,
            "context_summary": context_summary_from_state(state),
            "attachment_artifacts": list(state.get("attachment_artifacts", {}).values()),
            "compacted": compacted,
            "elapsed_ms": elapsed_ms,
        }

    # ---------- 模型调用 ----------
    async def _call_model(self, state: dict, session_id: str, emit: EmitFn):
        model_context = self.context_manager.build_model_context(state, self.agent_system_prompt)
        model_context = await hydrate_current_images(
            model_context,
            state.get("current_attachments", []),
            session_id=session_id,
            loader=self.attachment_loader,
        )
        started = time.perf_counter()
        first_token_at = None
        response = None
        estimated_input_tokens = message_tokens(model_context)
        model_name = getattr(self.model, "model_name", None) or getattr(self.model, "model", None)
        await emit({"kind": "harness_event", "event": {
            "event_type": "model/start", "component": "model", "node": "Agent",
            "status": "running", "model_name": model_name,
            "estimated_input_tokens": estimated_input_tokens,
        }})
        try:
            async for chunk in self.model_with_tools.astream(model_context):
                response = chunk if response is None else response + chunk
                if isinstance(chunk.content, str) and chunk.content:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                        await emit({"kind": "harness_event", "event": {
                            "event_type": "model/first_token", "component": "model",
                            "node": "Agent", "status": "streaming",
                            "ttft_ms": int((first_token_at - started) * 1000),
                        }})
                    await emit({"kind": "model_token", "node": "Agent", "content": chunk.content})
        except Exception as exc:
            await emit({"kind": "harness_event", "event": {
                "event_type": "model/error", "component": "model", "node": "Agent",
                "status": "error", "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
            }})
            raise
        finished = time.perf_counter()
        response = response or AIMessage(content="")
        if not response.id:
            response.id = str(uuid4())
        usage = getattr(response, "usage_metadata", None) or {}
        await emit({"kind": "harness_event", "event": {
            "event_type": "model/end", "component": "model", "node": "Agent",
            "status": "success", "duration_ms": int((finished - started) * 1000),
            "ttft_ms": int((first_token_at - started) * 1000) if first_token_at else None,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "requested_tools": [c.get("name", "unknown") for c in response.tool_calls],
        }})
        return response, usage

    # ---------- 工具执行 ----------
    async def _execute_tools(self, state: dict, response: AIMessage, emit: EmitFn):
        tool_messages: list[ToolMessage] = []
        traces: list[ToolTrace] = []
        for call in response.tool_calls:
            name = call.get("name", "unknown")
            args = call.get("args", {})
            tool = self.tools.get(name)
            started = time.perf_counter()
            await emit({"kind": "harness_event", "event": {
                "event_type": "tool/call", "component": "tool",
                "tool_name": name, "arguments": args, "status": "running",
            }})
            if tool is None:
                content = json.dumps({"error": f"未知工具：{name}", "error_type": "unknown_tool", "tool": name}, ensure_ascii=False)
                status = "error"
                error_type = "unknown_tool"
            else:
                try:
                    result = await asyncio.wait_for(tool.ainvoke(args), timeout=self.default_timeout)
                    content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                    status = "success"
                    error_type = None
                except asyncio.TimeoutError:
                    content = json.dumps({"error": f"{name} 执行超时", "error_type": "tool_timeout", "tool": name}, ensure_ascii=False)
                    status = "error"
                    error_type = "tool_timeout"
                except Exception as exc:
                    content = json.dumps({"error": str(exc), "error_type": type(exc).__name__, "tool": name}, ensure_ascii=False)
                    status = "error"
                    error_type = type(exc).__name__
            content, truncated = truncate_tool_payload(content, self.budget.tool_result_tokens)
            latency_ms = int((time.perf_counter() - started) * 1000)
            traces.append(ToolTrace(
                name=name, arguments=args, status=status, preview=content[:1200],
                latency_ms=latency_ms, error_type=error_type, truncated=truncated,
            ))
            await emit({"kind": "harness_event", "event": {
                "event_type": "tool/result" if status == "success" else "tool/error",
                "component": "tool", "tool_name": name, "status": status,
                "duration_ms": latency_ms, "error_type": error_type, "truncated": truncated,
            }})
            tool_messages.append(ToolMessage(
                content=content, tool_call_id=call.get("id", ""), name=name,
                status="error" if status == "error" else "success",
            ))
        return tool_messages, traces

    # ---------- Token 与指标 ----------
    @staticmethod
    def _accumulate(current: TurnTokenUsage, usage: dict, response: AIMessage) -> TurnTokenUsage:
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        total = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        return current.model_copy(update={
            "input_tokens": current.input_tokens + input_tokens,
            "output_tokens": current.output_tokens + output_tokens,
            "total_tokens": current.total_tokens + total,
            "model_calls": current.model_calls + 1,
            "estimated_calls": current.estimated_calls + (0 if usage.get("input_tokens") else 1),
        })

    def _build_context_metrics(self, state: dict, usage: dict) -> dict:
        summary = context_summary_from_state(state)
        ledger = sync_token_ledger(state.get("messages", []), state.get("token_ledger"), summary)
        estimated = ledger.active_message_tokens
        actual = usage.get("input_tokens")
        ledger = record_token_observation(ledger.model_dump(), estimated, actual)
        state["token_ledger"] = ledger.model_dump()
        metrics = ContextMetrics(
            context_window_tokens=self.budget.context_window_tokens,
            trigger_ratio=self.budget.trigger_ratio,
            trigger_tokens=self.budget.trigger_tokens,
            retain_ratio=self.budget.retain_ratio,
            recent_budget_tokens=self.budget.recent_tokens,
            summary_budget_tokens=self.budget.summary_tokens,
            tool_result_budget_tokens=self.budget.tool_result_tokens,
            active_message_tokens=ledger.active_message_tokens,
            summary_tokens=ledger.summary_tokens,
            model_input_tokens=actual or (estimated + ledger.protocol_overhead_tokens),
            model_input_source="api_usage" if actual else "estimated",
            messages_after=len(state.get("messages", [])),
            summary_version=int(state.get("summary_version", 0)),
        )
        return metrics.model_dump()

    @staticmethod
    def _answer_text(response: AIMessage) -> str:
        content = response.content
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, default=str)


def build_game_assistant(session_store, attachment_loader: AttachmentLoader | None = None) -> GameAgent:
    """组装依赖并返回无 LangGraph 的单 Agent Harness。"""
    model = create_model()
    budget = ContextBudget.from_env()
    context_manager = ContextManager(model, budget)
    return GameAgent(
        model=model,
        tools=AGENT_TOOLS,
        context_manager=context_manager,
        skill_registry=skill_registry,
        session_store=session_store,
        attachment_loader=attachment_loader,
    )
