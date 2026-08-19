"""有 Token 预算的滚动上下文管理器。

核心策略是“近期原始消息 + 较早结构化摘要”：达到预算阈值时只压缩较早的
完整对话轮次，保留近期消息原文，并通过 RemoveMessage 更新 LangGraph State。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.game_agent.models import (
    ContextSummary,
    ContextMetrics,
    HarnessState,
    TokenLedger,
)
from app.game_agent.prompts import COMPACTION_PROMPT, SUMMARY_REDUCE_PROMPT
from app.game_agent.structured import invoke_validated_json


@dataclass(frozen=True)
class ContextBudget:
    """上下文各区域的 Token 配额，全部可以通过环境变量调整。"""

    context_window_tokens: int
    trigger_ratio: float
    recent_tokens: int
    summary_tokens: int
    tool_result_tokens: int
    retain_ratio: float = 0.16
    compaction_retries: int = 1
    prune_threshold_tokens: int = 1800
    prune_retain_tokens: int = 600

    def __post_init__(self) -> None:
        if self.context_window_tokens <= 0:
            raise ValueError("context_window_tokens 必须大于 0")
        if not 0 < self.trigger_ratio < 1:
            raise ValueError("trigger_ratio 必须在 0 到 1 之间")
        if not 0 < self.retain_ratio < self.trigger_ratio:
            raise ValueError("retain_ratio 必须大于 0 且小于 trigger_ratio")
        if self.compaction_retries < 0:
            raise ValueError("compaction_retries 不能小于 0")
        if self.prune_retain_tokens <= 0 or self.prune_threshold_tokens <= self.prune_retain_tokens:
            raise ValueError("工具结果剪枝阈值必须大于保留预算")

    @property
    def trigger_tokens(self) -> int:
        """达到模型上下文上限的指定比例时开始压缩。"""
        return int(self.context_window_tokens * self.trigger_ratio)

    @classmethod
    def from_env(cls) -> "ContextBudget":
        """读取 DeepSeek Harness 风格的阈值与近期保留比例。"""
        context_window = int(os.getenv("GAME_EFFECTIVE_CONTEXT_TOKENS", "65536"))
        retain_ratio = float(os.getenv("GAME_CONTEXT_RETAIN_RATIO", "0.16"))
        legacy_recent = os.getenv("GAME_RECENT_BUDGET_TOKENS")
        return cls(
            context_window_tokens=context_window,
            trigger_ratio=float(os.getenv("GAME_CONTEXT_TRIGGER_RATIO", "0.8")),
            recent_tokens=int(legacy_recent) if legacy_recent else int(context_window * retain_ratio),
            summary_tokens=int(os.getenv("GAME_SUMMARY_BUDGET_TOKENS", "8192")),
            tool_result_tokens=int(os.getenv("GAME_TOOL_RESULT_BUDGET_TOKENS", "2500")),
            retain_ratio=retain_ratio,
            compaction_retries=int(os.getenv("GAME_COMPACTION_RETRIES", "1")),
            prune_threshold_tokens=int(os.getenv("GAME_TOOL_PRUNE_THRESHOLD_TOKENS", "1800")),
            prune_retain_tokens=int(os.getenv("GAME_TOOL_PRUNE_RETAIN_TOKENS", "600")),
        )


def message_tokens(messages: list[AnyMessage]) -> int:
    """估算文本 Token；图片成本由模型返回的真实 Usage 统一校准。"""
    if not messages:
        return 0
    normalized = []
    for message in messages:
        if not isinstance(message.content, list):
            normalized.append(message)
            continue
        text_parts = []
        for block in message.content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"text", "input_text"}:
                text_parts.append(str(block.get("text", "")))
        normalized.append(message.model_copy(update={"content": "\n".join(text_parts)}))
    return count_tokens_approximately(normalized)


def _message_key(message: AnyMessage, index: int = 0) -> str:
    """优先使用 LangChain 消息 ID，并兼容没有 ID 的旧 Checkpoint。"""
    if message.id:
        return str(message.id)
    return f"legacy:{index}:{message.type}:{hash(str(message.content))}"


def _message_fingerprint(message: AnyMessage) -> str:
    """检测同 ID 消息内容替换，避免继续沿用旧 Token 估值。"""
    payload = {
        "type": message.type,
        "content": message.content,
        "tool_calls": getattr(message, "tool_calls", None),
        "name": getattr(message, "name", None),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def sync_token_ledger(
    messages: list[AnyMessage],
    ledger_data: dict | None = None,
    summary: ContextSummary | None = None,
) -> TokenLedger:
    """只为新增或被替换的消息计算 Token，并清理已删除消息的记录。"""
    ledger = TokenLedger.model_validate(ledger_data or {})
    records = dict(ledger.message_tokens)
    fingerprints = dict(ledger.message_fingerprints)
    active_keys = set()
    for index, message in enumerate(messages):
        key = _message_key(message, index)
        fingerprint = _message_fingerprint(message)
        active_keys.add(key)
        if key not in records or fingerprints.get(key) != fingerprint:
            records[key] = message_tokens([message])
            fingerprints[key] = fingerprint
    records = {key: value for key, value in records.items() if key in active_keys}
    fingerprints = {key: value for key, value in fingerprints.items() if key in active_keys}
    ledger.message_tokens = records
    ledger.message_fingerprints = fingerprints
    ledger.active_message_tokens = sum(records.values())
    if summary is not None:
        ledger.summary_tokens = ContextManager._summary_tokens(summary)
    if ledger.protocol_overhead_tokens <= 0:
        ledger.protocol_overhead_tokens = int(os.getenv("GAME_PROMPT_OVERHEAD_TOKENS", "2500"))
    return ledger


def record_token_observation(
    ledger_data: dict | None,
    estimated_prompt_tokens: int,
    actual_prompt_tokens: int | None,
) -> TokenLedger:
    """记录本地估算与供应商 Usage；观测值不参与下一次上下文决策。"""
    ledger = TokenLedger.model_validate(ledger_data or {})
    ledger.last_estimated_prompt_tokens = estimated_prompt_tokens
    ledger.last_actual_prompt_tokens = actual_prompt_tokens
    return ledger


def split_into_complete_turns(messages: list[AnyMessage]) -> list[list[AnyMessage]]:
    """Group from each user message through all assistant/tool messages before the next user."""
    turns: list[list[AnyMessage]] = []
    current: list[AnyMessage] = []
    for message in messages:
        if message.type == "human" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    return turns


def split_by_recent_budget(
    messages: list[AnyMessage],
    recent_budget: int,
) -> tuple[list[AnyMessage], list[AnyMessage]]:
    turns = split_into_complete_turns(messages)
    if len(turns) <= 1:
        return [], messages

    selected: list[list[AnyMessage]] = []
    used = 0
    for turn in reversed(turns):
        tokens = message_tokens(turn)
        if selected and used + tokens > recent_budget:
            break
        selected.append(turn)
        used += tokens

    recent_turn_count = len(selected)
    expired_turns = turns[:-recent_turn_count] if recent_turn_count else turns[:-1]
    recent_turns = turns[-recent_turn_count:] if recent_turn_count else turns[-1:]
    return (
        [message for turn in expired_turns for message in turn],
        [message for turn in recent_turns for message in turn],
    )


def split_by_balanced_units(
    messages: list[AnyMessage],
    recent_budget: int,
) -> tuple[list[AnyMessage], list[AnyMessage]]:
    """单个超长 Turn 的降级边界：AI Tool Call 与其 Tool Result 永不拆开。"""
    units: list[list[AnyMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        unit = [message]
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            call_ids = {str(call.get("id", "")) for call in calls}
            cursor = index + 1
            while cursor < len(messages):
                candidate = messages[cursor]
                if not isinstance(candidate, ToolMessage):
                    break
                if str(candidate.tool_call_id) not in call_ids:
                    break
                unit.append(candidate)
                cursor += 1
            index = cursor
        else:
            index += 1
        units.append(unit)

    if len(units) <= 1:
        return [], messages
    selected: list[list[AnyMessage]] = []
    used = 0
    for unit in reversed(units):
        tokens = message_tokens(unit)
        if selected and used + tokens > recent_budget:
            break
        selected.append(unit)
        used += tokens
    recent_count = max(1, len(selected))
    expired_units = units[:-recent_count]
    recent_units = units[-recent_count:]
    return (
        [message for unit in expired_units for message in unit],
        [message for unit in recent_units for message in unit],
    )


def context_summary_from_state(state: HarnessState | dict) -> ContextSummary:
    """读取 ContextSummary，并兼容更早版本的 running_summary。"""
    current = state.get("context_summary")
    if current:
        return ContextSummary.model_validate(current)
    legacy = state.get("running_summary") or {}
    if not legacy:
        return ContextSummary()
    critical_context = [
        *[f"已识别游戏：{item}" for item in legacy.get("resolved_games", [])],
        *[f"已识别实体：{item}" for item in legacy.get("resolved_entities", [])],
        *[f"用户偏好或约束：{item}" for item in legacy.get("user_preferences", [])],
        *legacy.get("confirmed_facts", []),
        *[f"既有决策：{item}" for item in legacy.get("current_decisions", [])],
    ]
    if legacy.get("narrative"):
        critical_context.append(str(legacy["narrative"]))
    return ContextSummary(
        primary_request_and_intent=[legacy["active_goal"]] if legacy.get("active_goal") else [],
        pending_tasks=list(legacy.get("unresolved_questions", [])),
        critical_context=critical_context,
        important_tool_results=list(legacy.get("important_tool_results", [])),
        referenced_artifacts=list(legacy.get("attachment_refs", [])),
    )


class ContextManager:
    """决定何时压缩、生成 ContextSummary，并组装下一次模型输入。"""

    def __init__(
        self,
        summary_model: BaseChatModel | None,
        budget: ContextBudget | None = None,
    ):
        self.summary_model = summary_model
        self.budget = budget or ContextBudget.from_env()
        self.summary_timeout_seconds = float(os.getenv("GAME_SUMMARY_TIMEOUT_SECONDS", "12"))

    async def compact(
        self,
        state: HarnessState,
        force: bool = False,
        emit: Callable[[dict], None] | None = None,
        node: str = "ContextCompaction",
    ) -> dict:
        """在每次模型调用前测压，必要时剪枝并建立滚动摘要检查点。"""
        messages = state.get("messages", [])
        existing = context_summary_from_state(state)
        ledger = sync_token_ledger(messages, state.get("token_ledger"), existing)
        active_tokens = ledger.active_message_tokens
        summary_tokens = ledger.summary_tokens
        estimated_input_tokens = active_tokens + summary_tokens + ledger.protocol_overhead_tokens
        should_compact = force or state.get("force_compaction", False)
        should_compact = should_compact or (
            estimated_input_tokens >= self.budget.trigger_tokens
        )
        recent_budget = 0 if force else self.budget.recent_tokens
        # expired 将进入摘要，recent 继续以原始 Human/AI/Tool 消息保留。
        expired, recent = split_by_recent_budget(messages, recent_budget)
        if not expired and len(messages) > 1 and message_tokens(messages) > recent_budget:
            expired, recent = split_by_balanced_units(messages, recent_budget)

        previous_metrics = ContextMetrics.model_validate(state.get("context_metrics", {}))
        base_metrics = ContextMetrics(
            context_window_tokens=self.budget.context_window_tokens,
            trigger_ratio=self.budget.trigger_ratio,
            trigger_tokens=self.budget.trigger_tokens,
            retain_ratio=self.budget.retain_ratio,
            recent_budget_tokens=self.budget.recent_tokens,
            summary_budget_tokens=self.budget.summary_tokens,
            tool_result_budget_tokens=self.budget.tool_result_tokens,
            active_message_tokens=active_tokens,
            summary_tokens=summary_tokens,
            model_input_tokens=estimated_input_tokens,
            messages_before=len(messages),
            messages_after=len(messages),
            tokens_before_compaction=previous_metrics.tokens_before_compaction,
            tokens_after_compaction=previous_metrics.tokens_after_compaction,
            reduced_tokens=previous_metrics.reduced_tokens,
            converged=previous_metrics.converged,
            compacted_message_ids=previous_metrics.compacted_message_ids,
            retained_message_ids=previous_metrics.retained_message_ids,
            summary_version=state.get("summary_version", previous_metrics.summary_version),
            fallback_used=previous_metrics.fallback_used,
        )
        if emit is not None:
            emit({
                "event_type": "context/pressure",
                "component": "context",
                "node": node,
                "status": "measured",
                "source": "local_estimate",
                "estimated_input_tokens": estimated_input_tokens,
                "trigger_tokens": self.budget.trigger_tokens,
                "pressure_ratio": round(
                    estimated_input_tokens / self.budget.context_window_tokens, 4
                ),
                "will_compact": bool(should_compact),
            })
        if not should_compact:
            return {
                "context_metrics": base_metrics.model_dump(),
                "token_ledger": ledger.model_dump(),
                "compacted": bool(state.get("compacted", False)),
                "force_compaction": False,
            }

        attempt_id = str(uuid4())
        compacted_ids = [_message_key(message, index) for index, message in enumerate(expired)]
        retained_ids = [_message_key(message, index) for index, message in enumerate(recent)]
        lifecycle_events: list[dict] = []

        def publish(event_type: str, **payload) -> None:
            event = {
                "event_type": event_type,
                "node": node,
                "attempt_id": attempt_id,
                **payload,
            }
            lifecycle_events.append(event)
            if emit is not None:
                emit(event)

        publish(
            "compaction/start",
            trigger="manual" if force else "token_threshold",
            tokens_before=estimated_input_tokens,
            trigger_tokens=self.budget.trigger_tokens,
            retain_tokens=self.budget.recent_tokens,
            compacted_message_ids=compacted_ids,
            retained_message_ids=retained_ids,
        )

        working_messages, pruned_replacements, pruned_ids = self._prune_tool_results(
            messages,
            {_message_key(message, index) for index, message in enumerate(expired)},
        )
        if pruned_replacements:
            ledger_after_prune = sync_token_ledger(
                working_messages,
                ledger.model_dump(),
                existing,
            )
            after_prune = (
                ledger_after_prune.active_message_tokens
                + ledger_after_prune.summary_tokens
                + ledger_after_prune.protocol_overhead_tokens
            )
            if (
                not force
                and after_prune < self.budget.trigger_tokens
                and after_prune < estimated_input_tokens
            ):
                metrics = base_metrics.model_copy(update={
                    "active_message_tokens": ledger_after_prune.active_message_tokens,
                    "model_input_tokens": after_prune,
                    "messages_after": len(working_messages),
                    "pruned_tool_messages": len(pruned_ids),
                    "tokens_before_compaction": estimated_input_tokens,
                    "tokens_after_compaction": after_prune,
                    "reduced_tokens": max(0, estimated_input_tokens - after_prune),
                    "converged": True,
                    "retained_message_ids": [
                        _message_key(message, index)
                        for index, message in enumerate(working_messages)
                    ],
                })
                publish(
                    "compaction/end",
                    status="success",
                    mode="tool_result_pruning",
                    tokens_after=after_prune,
                    reduced_tokens=max(0, estimated_input_tokens - after_prune),
                    converged=True,
                    pruned_message_ids=pruned_ids,
                )
                return {
                    "messages": pruned_replacements,
                    "context_metrics": metrics.model_dump(),
                    "token_ledger": ledger_after_prune.model_dump(),
                    "compacted": True,
                    "force_compaction": False,
                    "compaction_count": state.get("compaction_count", 0) + 1,
                    "compaction_events": lifecycle_events,
                }

        if not expired:
            publish(
                "compaction/end",
                status="failed",
                mode="no_compactable_region",
                tokens_after=estimated_input_tokens,
                reduced_tokens=0,
                converged=False,
                error="当前上下文没有可安全压缩的闭合消息区域",
            )
            return {
                "messages": pruned_replacements,
                "context_metrics": base_metrics.model_copy(update={
                    "converged": False,
                    "tokens_before_compaction": estimated_input_tokens,
                    "tokens_after_compaction": estimated_input_tokens,
                    "pruned_tool_messages": len(pruned_ids),
                }).model_dump(),
                "token_ledger": ledger.model_dump(),
                "compacted": bool(state.get("compacted", False)),
                "force_compaction": False,
                "compaction_events": lifecycle_events,
            }

        # 摘要应基于剪枝后的消息，避免再次把整段旧工具正文送入摘要模型。
        expired_keys = set(compacted_ids)
        expired = [
            message for index, message in enumerate(working_messages)
            if _message_key(message, index) in expired_keys
        ]

        summary, fallback_used = await self._generate_summary(existing, expired)
        summary = await self._enforce_summary_budget(summary)
        next_summary_version = state.get("summary_version", 0) + 1
        # LangGraph 的消息 Reducer 通过 RemoveMessage 真正移除已摘要的历史消息。
        removals = [RemoveMessage(id=message.id) for message in expired if message.id]
        summary_tokens = self._summary_tokens(summary)
        recent_keys = {
            _message_key(message, index) for index, message in enumerate(recent)
        }
        ledger.message_tokens = {
            key: value for key, value in ledger.message_tokens.items() if key in recent_keys
        }
        ledger.message_fingerprints = {
            key: value for key, value in ledger.message_fingerprints.items() if key in recent_keys
        }
        ledger.active_message_tokens = sum(ledger.message_tokens.values())
        ledger.summary_tokens = summary_tokens
        tokens_after = ledger.active_message_tokens + summary_tokens + ledger.protocol_overhead_tokens
        retry_count = 0
        while (
            not force
            and tokens_after >= self.budget.trigger_tokens
            and retry_count < self.budget.compaction_retries
        ):
            retry_count += 1
            summary = self._deterministic_reduce(
                summary,
                max(256, summary_tokens // 2),
            )
            summary_tokens = self._summary_tokens(summary)
            ledger.summary_tokens = summary_tokens
            tokens_after = ledger.active_message_tokens + summary_tokens + ledger.protocol_overhead_tokens
        publish(
            "compaction/summary",
            summary_tokens=summary_tokens,
            summary_version=next_summary_version,
            fallback_used=fallback_used,
            retry_count=retry_count,
        )
        metrics = base_metrics.model_copy(update={
            "active_message_tokens": ledger.active_message_tokens,
            "summary_tokens": summary_tokens,
            "model_input_tokens": (
                ledger.active_message_tokens + summary_tokens + ledger.protocol_overhead_tokens
            ),
            "messages_after": len(recent),
            "compacted_messages": len(expired),
            "pruned_tool_messages": len(pruned_ids),
            "tokens_before_compaction": estimated_input_tokens,
            "tokens_after_compaction": tokens_after,
            "reduced_tokens": max(
                0,
                estimated_input_tokens - tokens_after,
            ),
            "converged": (
                tokens_after < estimated_input_tokens
                and (force or tokens_after < self.budget.trigger_tokens)
            ),
            "compacted_message_ids": compacted_ids,
            "retained_message_ids": retained_ids,
            "summary_version": next_summary_version,
            "fallback_used": fallback_used,
        })
        publish(
            "compaction/end",
            status="success" if metrics.converged else "non_converged",
            mode="summary",
            tokens_after=metrics.tokens_after_compaction,
            reduced_tokens=metrics.reduced_tokens,
            converged=metrics.converged,
            compacted_message_ids=compacted_ids,
            retained_message_ids=retained_ids,
        )
        update = {
            "messages": [*pruned_replacements, *removals],
            "context_summary": summary.model_dump(),
            "running_summary": {},
            "context_metrics": metrics.model_dump(),
            "token_ledger": ledger.model_dump(),
            "compacted": True,
            "force_compaction": False,
            "compaction_count": state.get("compaction_count", 0) + 1,
            "summary_version": next_summary_version,
            "compaction_events": lifecycle_events,
        }
        return update

    def build_model_context(
        self,
        state: HarnessState,
        system_prompt: str,
        extra_system_messages: list[SystemMessage] | None = None,
    ) -> list[AnyMessage]:
        """按 System Prompt、ContextSummary、近期消息的顺序组装输入。"""
        messages: list[AnyMessage] = [SystemMessage(content=system_prompt)]
        summary = context_summary_from_state(state)
        if any(summary.model_dump().values()):
            messages.append(SystemMessage(
                content="【ContextSummary：较早历史的结构化任务摘要】\n"
                + json.dumps(summary.model_dump(), ensure_ascii=False)
            ))
        if extra_system_messages:
            messages.extend(extra_system_messages)
        messages.extend(state.get("messages", []))
        return messages

    def _prune_tool_results(
        self,
        messages: list[AnyMessage],
        preferred_ids: set[str],
    ) -> tuple[list[AnyMessage], list[ToolMessage], list[str]]:
        """仅在上下文承压时缩减旧大型 Tool Result，并保留可审计预览。"""
        working = list(messages)
        replacements: list[ToolMessage] = []
        pruned_ids: list[str] = []
        latest_tool_id = next(
            (str(message.id) for message in reversed(messages) if isinstance(message, ToolMessage) and message.id),
            None,
        )
        for index, message in enumerate(messages):
            if not isinstance(message, ToolMessage):
                continue
            key = _message_key(message, index)
            if key == latest_tool_id or (preferred_ids and key not in preferred_ids):
                continue
            if message_tokens([message]) <= self.budget.prune_threshold_tokens:
                continue
            original = message.content if isinstance(message.content, str) else json.dumps(
                message.content, ensure_ascii=False, default=str
            )
            compact_content = json.dumps({
                "status": "pruned",
                "tool": message.name,
                "note": "旧工具结果因上下文压力被裁剪；保留以下预览供后续推理。",
                "preview": self._truncate_text(original, self.budget.prune_retain_tokens),
            }, ensure_ascii=False)
            replacement = message.model_copy(update={"content": compact_content})
            working[index] = replacement
            replacements.append(replacement)
            pruned_ids.append(key)
        return working, replacements, pruned_ids

    async def _generate_summary(
        self,
        existing: ContextSummary,
        expired_messages: list[AnyMessage],
    ) -> tuple[ContextSummary, bool]:
        """把过期轮次的文字与图片一起交给摘要模型。"""
        if self.summary_model is None:
            return self._fallback_summary(existing, expired_messages), True
        instruction = HumanMessage(content=(
            f"{COMPACTION_PROMPT}\n\n"
            f"Existing ContextSummary：{json.dumps(existing.model_dump(), ensure_ascii=False)}\n"
            f"Summary Token Budget：{self.budget.summary_tokens}"
        ))
        try:
            summary = await asyncio.wait_for(
                invoke_validated_json(
                    self.summary_model,
                    ContextSummary,
                    [*expired_messages, instruction],
                    max_tokens=self.budget.summary_tokens,
                ),
                timeout=self.summary_timeout_seconds,
            )
            return summary, False
        except Exception:
            return self._fallback_summary(existing, expired_messages), True

    async def _enforce_summary_budget(self, summary: ContextSummary) -> ContextSummary:
        """摘要超额时先尝试模型精简，失败后按字段优先级确定性淘汰。"""
        if self._summary_tokens(summary) <= self.budget.summary_tokens:
            return summary
        if self.summary_model is None:
            return self._deterministic_reduce(summary)
        try:
            reduced = await asyncio.wait_for(
                invoke_validated_json(
                    self.summary_model,
                    ContextSummary,
                    [HumanMessage(content=(
                        f"{SUMMARY_REDUCE_PROMPT}\n预算：{self.budget.summary_tokens} tokens\n"
                        f"待压缩内容：{json.dumps(summary.model_dump(), ensure_ascii=False)}"
                    ))],
                    max_tokens=self.budget.summary_tokens,
                ),
                timeout=self.summary_timeout_seconds,
            )
            if self._summary_tokens(reduced) <= self.budget.summary_tokens:
                return reduced
            summary = reduced
        except Exception:
            pass
        return self._deterministic_reduce(summary)

    def _fallback_summary(
        self,
        existing: ContextSummary,
        expired_messages: list[AnyMessage],
    ) -> ContextSummary:
        """摘要模型超时或不可用时立即降级，避免阻塞整轮对话。"""
        summary = existing.model_copy(deep=True)
        serialized = json.dumps(
            [self._fallback_message(message) for message in expired_messages],
            ensure_ascii=False,
        )
        summary.critical_context.append(
            self._truncate_text(serialized, self.budget.summary_tokens)
        )
        return self._deterministic_reduce(summary)

    def _deterministic_reduce(
        self,
        summary: ContextSummary,
        target_tokens: int | None = None,
    ) -> ContextSummary:
        """不调用模型的有界裁剪，保证任何异常下摘要都不会无限增长。"""
        data = summary.model_dump()
        target = max(
            target_tokens if target_tokens is not None else self.budget.summary_tokens,
            self._summary_tokens(ContextSummary()),
        )
        data["next_step"] = data["next_step"][:400]
        for field in ("important_tool_results", "errors_and_recoveries", "current_work"):
            data[field] = [item[:320] for item in data[field][-8:]]
        for field in (
            "primary_request_and_intent",
            "key_concepts",
            "completed_work",
            "pending_tasks",
            "critical_context",
            "referenced_artifacts",
        ):
            data[field] = [item[:200] for item in data[field][-12:]]
        reduced = ContextSummary.model_validate(data)
        eviction_order = (
            "important_tool_results",
            "completed_work",
            "errors_and_recoveries",
            "key_concepts",
            "referenced_artifacts",
            "critical_context",
            "current_work",
            "pending_tasks",
            "primary_request_and_intent",
        )
        while self._summary_tokens(reduced) > target:
            changed = False
            for field in eviction_order:
                values = getattr(reduced, field)
                if values:
                    setattr(reduced, field, values[1:])
                    changed = True
                    break
            if not changed:
                reduced.next_step = reduced.next_step[: max(0, len(reduced.next_step) // 2)]
                if not reduced.next_step:
                    break
        return reduced

    @staticmethod
    def _fallback_message(message: AnyMessage) -> dict:
        """降级摘要只保留文本和图片占位，不把 Base64 写入 ContextSummary。"""
        content = message.content
        if isinstance(content, str):
            content = content[:3200]
        elif isinstance(content, list):
            content = [
                block
                if isinstance(block, dict) and block.get("type") in {"text", "input_text"}
                else {"type": "image", "note": "摘要模型不可用，未保留图片语义"}
                for block in content
            ]
        return {"type": message.type, "content": content}

    @staticmethod
    def _truncate_text(text: str, max_tokens: int) -> str:
        return text[: max_tokens * 4]

    @staticmethod
    def _summary_tokens(summary: ContextSummary) -> int:
        if not any(summary.model_dump().values()):
            return 0
        content = json.dumps(summary.model_dump(), ensure_ascii=False)
        return count_tokens_approximately([HumanMessage(content=content)])
