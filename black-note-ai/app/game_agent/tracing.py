"""Harness 级可观测性（精简版）。

工具执行已移入 agent.py，本模块只保留：工具结果裁剪、以及一次请求的
节点/步骤轨迹与 Token 指标记录。不再依赖 LangGraph。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import ToolMessage

from app.game_agent.models import TurnTokenUsage


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

        results = payload.get("results", [])
        if isinstance(results, list):
            payload["results"] = results[:3]
            compact = json.dumps(payload, ensure_ascii=False)
            if len(compact) <= rough_limit:
                return compact, True
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    suffix = "\n[truncated]"
    return content[: max(0, rough_limit - len(suffix))] + suffix, True


class HarnessTracer:
    """一次请求对应一个实例，统一生成可持久化的节点轨迹和运行日志。"""

    NODE_LABELS = {
        "TurnContext": "构建本轮上下文",
        "ContextCompaction": "检查上下文预算",
        "Agent": "模型判断与生成",
        "ToolExecution": "执行工具",
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
        elif node == "Agent":
            event["detail"] = "已生成最终回答" if not update.get("tool_calls") else "请求工具"
            event["tool_calls"] = update.get("tool_calls", [])
            event["model_metrics"] = dict(self.current_model_metrics)
        elif node == "ToolExecution":
            event["detail"] = f"本批完成 {update.get('tool_count', 0)} 个工具调用"
            event["tool_trace"] = update.get("tool_trace", [])
        else:
            event["detail"] = self.NODE_LABELS.get(node, node)

        self.events.append(event)
        self.previous_node = node
        self.node_started = time.perf_counter()
        logging.info(
            "Harness node run_id=%s turn=%s node=%s duration_ms=%s",
            self.run_id, self.turn_number, node, event["duration_ms"],
        )
        return event

    def record_custom(self, event: dict) -> list[dict]:
        """把模型事件归入稳定的 Turn/Step 语义轨迹。"""
        if event.get("kind") != "harness_event" or not isinstance(event.get("event"), dict):
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

    def finish(self, token_usage: TurnTokenUsage) -> int:
        elapsed_ms = int((time.perf_counter() - self.started) * 1000)
        logging.info(
            "Harness complete run_id=%s turn=%s elapsed_ms=%s model_calls=%s "
            "input_tokens=%s output_tokens=%s total_tokens=%s",
            self.run_id, self.turn_number, elapsed_ms, token_usage.model_calls,
            token_usage.input_tokens, token_usage.output_tokens, token_usage.total_tokens,
        )
        return elapsed_ms
