"""Harness 级可观测性。

ToolNode 负责执行工具；本模块只记录图节点、工具调用和本轮 Token 消耗，
避免把执行、状态更新与前端轨迹混在同一个 Runtime 类中。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.game_agent.models import ToolTrace, TurnTokenUsage


def truncate_tool_payload(content: str, token_budget: int) -> tuple[str, bool]:
    """把传回模型的工具结果限制在预算内，并尽量保持搜索结果为合法 JSON。"""
    rough_limit = max(32, token_budget * 4)
    if len(content) <= rough_limit:
        return content, False
    try:
        payload = json.loads(content)
        if payload.get("error"):
            for message_limit in (240, 120, 60):
                compact = json.dumps({
                    "error": str(payload.get("error", ""))[:message_limit],
                    "error_type": payload.get("error_type", "tool_error"),
                    "tool": payload.get("tool", "unknown"),
                }, ensure_ascii=False)
                if len(compact) <= rough_limit:
                    return compact, True
            return json.dumps({"error": "tool_error"}, ensure_ascii=False), True

        output_items = payload.get("output_items", [])
        search_message = next(
            (item for item in output_items if item.get("type") == "search_message"),
            None,
        )
        if search_message is not None:
            payload.pop("trace", None)
            for evidence in search_message.get("evidence", []):
                evidence["snippet"] = evidence.get("snippet", "")[:320]
                evidence["relevant_passages"] = [
                    passage[:500]
                    for passage in evidence.get("relevant_passages", [])[:2]
                ]
            compact = json.dumps(payload, ensure_ascii=False)
            while len(compact) > rough_limit and len(search_message.get("evidence", [])) > 1:
                search_message["evidence"].pop()
                compact = json.dumps(payload, ensure_ascii=False)
            if len(compact) > rough_limit:
                search_message["evidence"] = []
                search_message["missing_information"] = [
                    "搜索证据超过 Tool Result 预算，详细步骤已保留在 Harness Trace。"
                ]
                compact = json.dumps(payload, ensure_ascii=False)
            if len(compact) > rough_limit:
                compact = '{"error":"budget","output_items":[]}'
            return compact, True
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    suffix = "\n[truncated]"
    return content[: max(0, rough_limit - len(suffix))] + suffix, True


def _message_content(message: ToolMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, ensure_ascii=False, default=str)


def _trace_from_result(
    name: str,
    arguments: dict,
    content: str,
    status: str,
    latency_ms: int,
    truncated: bool,
    *,
    execute_ms: int = 0,
    post_process_ms: int = 0,
    timeout_seconds: float | None = None,
) -> ToolTrace:
    steps: list[dict] = []
    output_items: list[dict] = []
    normalized_status = "error" if status == "error" else "success"
    error_type = None
    try:
        parsed = json.loads(content)
        if parsed.get("error"):
            normalized_status = "error"
            error_type = parsed.get("error_type", "tool_error")
        output_items = parsed.get("output_items", [])
        steps = parsed.get("trace", {}).get("pipeline", parsed.get("pipeline", []))
        search_call = next(
            (item for item in output_items if item.get("type") == "web_search_call"),
            {},
        )
        if search_call.get("status") == "failed":
            normalized_status = "error"
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return ToolTrace(
        name=name,
        arguments=arguments,
        status=normalized_status,
        preview=content[:1200],
        latency_ms=latency_ms,
        execute_ms=execute_ms,
        post_process_ms=post_process_ms,
        timeout_seconds=timeout_seconds,
        error_type=error_type,
        truncated=truncated,
        steps=steps,
        output_items=output_items,
    )


def create_tool_call_wrapper(
    *,
    result_token_budget: int,
    default_timeout_seconds: float,
    tool_timeouts: dict[str, float] | None = None,
):
    """为官方 ToolNode 增加超时、结果预算和可观测元数据。"""
    timeouts = tool_timeouts or {}

    async def wrapper(
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        call = request.tool_call
        name = call.get("name", "unknown")
        arguments = call.get("args", {})
        timeout_seconds = timeouts.get(name, default_timeout_seconds)
        started = time.perf_counter()
        request.runtime.stream_writer({
            "kind": "harness_event",
            "event": {
                "event_type": "tool/call",
                "component": "tool",
                "tool_call_id": call.get("id", name),
                "tool_name": name,
                "arguments": arguments,
                "timeout_seconds": timeout_seconds,
                "status": "running",
            },
        })
        try:
            result = await asyncio.wait_for(execute(request), timeout=timeout_seconds)
            if not isinstance(result, ToolMessage):
                return result
        except asyncio.TimeoutError:
            result = ToolMessage(
                content=json.dumps({
                    "error": f"{name} 执行超过 {timeout_seconds:g} 秒，已被 Harness 取消。请根据已有信息继续回答。",
                    "error_type": "tool_timeout",
                    "tool": name,
                    "timeout_seconds": timeout_seconds,
                }, ensure_ascii=False),
                tool_call_id=call.get("id", name),
                name=name,
                status="error",
            )
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            result = ToolMessage(
                content=json.dumps({
                    "error": detail,
                    "error_type": exc.__class__.__name__,
                    "tool": name,
                }, ensure_ascii=False),
                tool_call_id=call.get("id", name),
                name=name,
                status="error",
            )

        executed = time.perf_counter()
        original_content = _message_content(result)
        content, truncated = truncate_tool_payload(original_content, result_token_budget)
        finished = time.perf_counter()
        execute_ms = int((executed - started) * 1000)
        post_process_ms = int((finished - executed) * 1000)
        latency_ms = int((finished - started) * 1000)
        trace = _trace_from_result(
            name,
            arguments,
            original_content,
            getattr(result, "status", "success"),
            latency_ms,
            truncated,
            execute_ms=execute_ms,
            post_process_ms=post_process_ms,
            timeout_seconds=timeout_seconds,
        ).model_copy(update={"preview": content[:1200]})
        artifact = dict(result.artifact) if isinstance(result.artifact, dict) else {}
        artifact["harness_trace"] = trace.model_dump()
        traced_result = result.model_copy(update={
            "content": content,
            "status": trace.status,
            # artifact 会随 Checkpoint 保存，但不会作为 ToolMessage 正文发给模型。
            "artifact": artifact,
        })
        request.runtime.stream_writer({
            "kind": "harness_event",
            "event": {
                "event_type": "tool/result" if trace.status == "success" else "tool/error",
                "component": "tool",
                "tool_call_id": call.get("id", name),
                "tool_name": name,
                "status": trace.status,
                "duration_ms": latency_ms,
                "execute_ms": trace.execute_ms,
                "post_process_ms": trace.post_process_ms,
                "timeout_seconds": trace.timeout_seconds,
                "error_type": trace.error_type,
                "truncated": trace.truncated,
            },
        })
        logging.info(
            "Harness tool_call name=%s status=%s latency_ms=%s truncated=%s",
            name,
            trace.status,
            latency_ms,
            truncated,
        )
        return traced_result

    return wrapper


class HarnessTracer:
    """一次请求对应一个实例，统一生成可持久化的节点轨迹和运行日志。"""

    NODE_LABELS = {
        "TurnContext": "构建本轮上下文",
        "ContextCompaction": "检查上下文预算",
        "Agent": "模型判断与生成",
        "ToolExecution": "执行工具",
        "ProcessToolResults": "处理工具结果",
        "ForceFinish": "工具轮次上限收敛",
    }

    def __init__(self, run_id: str, turn_number: int):
        self.run_id = run_id
        self.turn_number = turn_number
        self.started = time.perf_counter()
        self.node_started = self.started
        self.previous_node: str | None = None
        self.step_number = 0
        self.step_started: float | None = None
        self.current_model_metrics: dict[str, Any] = {}
        self.events: list[dict] = []

    def record_node(self, node: str, update: dict) -> dict:
        finished = time.perf_counter()
        event = {
            "event_type": "node",
            "node": node,
            "label": self.NODE_LABELS.get(node, node),
            "edge": f"{self.previous_node or 'START'} → {node}",
            "duration_ms": int((finished - self.node_started) * 1000),
            "elapsed_ms": int((finished - self.started) * 1000),
            "step_number": self.step_number or None,
        }
        if node == "ContextCompaction":
            event["detail"] = "已自动压缩较早轮次" if update.get("compacted") else "当前上下文仍在预算内"
            event["compacted"] = bool(update.get("compacted"))
            event["context_metrics"] = update.get("context_metrics", {})
            event["compaction_events"] = update.get("compaction_events", [])
        elif node == "Agent":
            messages = update.get("messages", [])
            tool_calls = getattr(messages[-1], "tool_calls", []) if messages else []
            event["detail"] = (
                "请求工具：" + "、".join(call["name"] for call in tool_calls)
                if tool_calls else "已生成最终回答"
            )
            event["tool_calls"] = tool_calls
            event["model_metrics"] = dict(self.current_model_metrics)
        elif node == "ToolExecution":
            traces = [
                message.artifact.get("harness_trace")
                for message in update.get("messages", [])
                if isinstance(message, ToolMessage)
                and isinstance(message.artifact, dict)
                and message.artifact.get("harness_trace")
            ]
            names = list(dict.fromkeys(trace.get("name", "工具") for trace in traces))
            event["label"] = "加载专业能力" if names == ["load_skill"] else (
                "执行 " + "、".join(names) if names else "执行工具"
            )
            event["detail"] = f"本批完成 {len(traces)} 个工具调用"
            event["tool_trace"] = traces
        elif node == "ProcessToolResults":
            event["detail"] = "已解析工具结果并登记 Skill、轨迹、轮次和 Token 账本"
        elif node == "ForceFinish":
            event["detail"] = "工具轮次达到上限，已基于现有证据生成回答"
            event["tool_trace"] = update.get("tool_trace", [])
            event["model_metrics"] = dict(self.current_model_metrics)
        else:
            event["detail"] = self.NODE_LABELS.get(node, node)

        self.events.append(event)
        self.previous_node = node
        self.node_started = time.perf_counter()
        logging.info(
            "Harness node run_id=%s turn=%s node=%s duration_ms=%s",
            self.run_id,
            self.turn_number,
            node,
            event["duration_ms"],
        )
        return event

    def observe_custom(self, event: dict) -> None:
        if event.get("kind") == "tool_call":
            trace = event.get("trace", {})
            logging.info(
                "Harness custom run_id=%s tool=%s status=%s",
                self.run_id,
                trace.get("name"),
                trace.get("status"),
            )

    def _close_step(self, status: str = "completed") -> dict | None:
        if self.step_started is None:
            return None
        event = {
            "event_type": "step/end",
            "component": "harness",
            "step_number": self.step_number,
            "status": status,
            "duration_ms": int((time.perf_counter() - self.step_started) * 1000),
            "elapsed_ms": int((time.perf_counter() - self.started) * 1000),
        }
        self.step_started = None
        self.events.append(event)
        return event

    def record_custom(self, event: dict) -> list[dict]:
        """把模型、工具和压缩事件归入稳定的 Turn/Step 语义轨迹。"""
        if event.get("kind") != "harness_event" or not isinstance(event.get("event"), dict):
            self.observe_custom(event)
            return []
        payload = dict(event["event"])
        emitted = []
        if payload.get("event_type") == "model/start":
            previous = self._close_step()
            if previous is not None:
                emitted.append(previous)
            self.step_number += 1
            self.step_started = time.perf_counter()
            self.current_model_metrics = {}
            step_start = {
                "event_type": "step/start",
                "component": "harness",
                "step_number": self.step_number,
                "status": "running",
                "node": payload.get("node"),
                "elapsed_ms": int((time.perf_counter() - self.started) * 1000),
            }
            self.events.append(step_start)
            emitted.append(step_start)
        payload["step_number"] = self.step_number or 1
        payload.setdefault("elapsed_ms", int((time.perf_counter() - self.started) * 1000))
        self.events.append(payload)
        emitted.append(payload)
        if payload.get("event_type") == "model/end":
            self.current_model_metrics = {
                key: payload.get(key)
                for key in (
                    "duration_ms", "ttft_ms", "generation_ms", "input_tokens",
                    "output_tokens", "tokens_per_second", "output_chunks",
                )
            }
            if not payload.get("requested_tools"):
                closed = self._close_step()
                if closed is not None:
                    emitted.append(closed)
        elif payload.get("event_type") == "model/error":
            closed = self._close_step("failed")
            if closed is not None:
                emitted.append(closed)
        return emitted

    def finish(self, token_usage: TurnTokenUsage) -> int:
        elapsed_ms = int((time.perf_counter() - self.started) * 1000)
        logging.info(
            "Harness complete run_id=%s turn=%s elapsed_ms=%s model_calls=%s input_tokens=%s output_tokens=%s total_tokens=%s estimated_calls=%s",
            self.run_id,
            self.turn_number,
            elapsed_ms,
            token_usage.model_calls,
            token_usage.input_tokens,
            token_usage.output_tokens,
            token_usage.total_tokens,
            token_usage.estimated_calls,
        )
        return elapsed_ms
