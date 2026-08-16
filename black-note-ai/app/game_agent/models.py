"""GameRover 的共享数据协议。

这里不执行业务逻辑，只定义 LangGraph State、接口请求响应、工具轨迹和各种
结构化模型。集中定义可以避免 graph、memory、tools 之间使用不一致的字典。
"""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator
from typing_extensions import TypedDict


class VisualMemory(BaseModel):
    """历史图片压缩后保留在 RunningSummary 中的任务相关视觉记忆。"""

    source_message_id: str = ""
    image_type: str = "unknown"
    game: str = ""
    entities: list[str] = Field(default_factory=list)
    scene: str = ""
    ocr_text: list[str] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    user_relevance: str = ""


class RunningSummary(BaseModel):
    """较早对话压缩后的长期滚动状态，而不是面向用户的自然语言摘要。"""

    # 当前仍在推进的任务必须优先保留，防止压缩后 Agent 丢失目标。
    active_goal: str = ""
    # 以下字段按语义分类，方便下一次压缩时去重和淘汰过期信息。
    resolved_games: list[str] = Field(default_factory=list)
    resolved_entities: list[str] = Field(default_factory=list)
    user_preferences: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    current_decisions: list[str] = Field(default_factory=list)
    important_tool_results: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    visual_memories: list[VisualMemory] = Field(default_factory=list)
    attachment_refs: list[str] = Field(default_factory=list)
    narrative: str = ""


class TokenLedger(BaseModel):
    """按消息 ID 增量维护的上下文 Token 估算账本。"""

    message_tokens: dict[str, int] = Field(default_factory=dict)
    message_fingerprints: dict[str, str] = Field(default_factory=dict)
    active_message_tokens: int = 0
    summary_tokens: int = 0
    protocol_overhead_tokens: int = 0
    last_estimated_prompt_tokens: int = 0
    last_actual_prompt_tokens: int | None = None


class ContextMetrics(BaseModel):
    """一次上下文预算检查的可观测指标，供 Harness 面板展示。"""

    # 配置预算。
    context_window_tokens: int = 0
    trigger_ratio: float = 0.8
    trigger_tokens: int = 0
    retain_ratio: float = 0.16
    recent_budget_tokens: int = 0
    summary_budget_tokens: int = 0
    tool_result_budget_tokens: int = 0
    # 实际占用：Active 是近期原始消息，Summary 是被压缩的较早状态。
    active_message_tokens: int = 0
    summary_tokens: int = 0
    model_input_tokens: int = 0
    model_input_source: Literal["estimated", "api_usage"] = "estimated"
    messages_before: int = 0
    messages_after: int = 0
    compacted_messages: int = 0
    pruned_tool_messages: int = 0
    tokens_before_compaction: int = 0
    tokens_after_compaction: int = 0
    reduced_tokens: int = 0
    converged: bool = False
    compacted_message_ids: list[str] = Field(default_factory=list)
    retained_message_ids: list[str] = Field(default_factory=list)
    summary_version: int = 0
    fallback_used: bool = False


class TurnTokenUsage(BaseModel):
    """当前一轮内全部主模型调用的 Token 汇总。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    estimated_calls: int = 0


class ToolTrace(BaseModel):
    """一次 Tool Call 的审计记录，不等同于传回模型的 ToolMessage。"""

    name: str
    arguments: dict = Field(default_factory=dict)
    status: Literal["success", "error"]
    preview: str
    latency_ms: int
    execute_ms: int = 0
    post_process_ms: int = 0
    timeout_seconds: float | None = None
    error_type: str | None = None
    truncated: bool = False
    steps: list[dict] = Field(default_factory=list)
    output_items: list[dict] = Field(default_factory=list)


class HarnessState(TypedDict, total=False):
    """LangGraph Checkpoint 中持久化的完整会话状态。

    total=False 表示节点只需返回自己修改的字段；LangGraph Reducer 负责合并。
    messages 使用 add_messages，因此新消息会追加，RemoveMessage 会按 ID 删除。
    """

    # 对话与压缩记忆。
    messages: Annotated[list[AnyMessage], add_messages]
    running_summary: dict
    # 原图只存在于近期 HumanMessage 与数据库附件；历史视觉语义进入 RunningSummary。
    pending_attachments: list[dict]
    attachment_artifacts: dict[str, dict]
    # Harness 可观测数据和计数器。
    tool_trace: list[dict]
    # Skill 正文不写入消息历史；这里只保存本轮激活记录和按需 reference 键。
    active_skills: list[str]
    loaded_skill_resources: list[str]
    skill_trace: list[dict]
    context_metrics: dict
    compaction_events: list[dict]
    token_ledger: dict
    turn_token_usage: dict
    llm_calls: int
    tool_rounds: int
    turn_count: int
    compaction_count: int
    summary_version: int
    compacted: bool
    force_compaction: bool


class AttachmentInput(BaseModel):
    """前端上传到聊天接口的单个附件。"""

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    size: int = Field(ge=0, le=10 * 1024 * 1024)
    data_url: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """开始一轮 Agent 执行所需的输入。"""

    question: str = ""
    session_id: str = "default"
    images: list[str] = Field(default_factory=list)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=5)
    force_compaction: bool = False

    @model_validator(mode="after")
    def require_content(self):
        if not self.question.strip() and not self.images and not self.attachments:
            raise ValueError("question or attachment is required")
        if any(not item.mime_type.startswith("image/") for item in self.attachments):
            raise ValueError("当前阶段只支持图片附件")
        if sum(item.size for item in self.attachments) > 20 * 1024 * 1024:
            raise ValueError("total attachment size cannot exceed 20MB")
        return self


class ChatResponse(BaseModel):
    """一轮执行完成后返回给前端的答案和 Harness 状态摘要。"""

    answer: str
    tool_trace: list[ToolTrace]
    context_metrics: ContextMetrics
    token_usage: TurnTokenUsage
    running_summary: RunningSummary
    attachment_artifacts: list[dict]
    compacted: bool


class SessionRenameRequest(BaseModel):
    """历史会话重命名接口的输入。"""
    title: str = Field(min_length=1, max_length=100)
