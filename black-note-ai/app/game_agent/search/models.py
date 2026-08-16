from __future__ import annotations

from hashlib import sha1
from typing import Literal

from pydantic import BaseModel, Field

# 表示搜索引擎返回的一条结果
class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    query: str
    source_domain: str = ""
    source_type: str = "unknown"
    rank: int = 0

# 表示抓取后的网页
class FetchedPage(BaseModel):
    url: str
    title: str = ""
    text: str = ""
    published_at: str | None = None
    error: str | None = None

# 表示最终提供给 Agent 的证据
class Evidence(BaseModel):
    evidence_id: str
    title: str
    url: str
    source_domain: str
    source_type: str
    query: str
    snippet: str
    relevant_passages: list[str] = Field(default_factory=list)
    published_at: str | None = None
    relevance_score: float = 0

# 记录 Search Harness 的执行步骤
class SearchStep(BaseModel):
    name: str
    label: str
    status: str = "success"
    detail: str


class SearchPlan(BaseModel):
    intent: Literal["fact", "news", "guide", "comparison", "research"] = "research"
    queries: list[str] = Field(min_length=1, max_length=4)
    rationale: str = ""
    preferred_sources: list[str] = Field(default_factory=list)
    freshness_days: int | None = None


class SearchAction(BaseModel):
    type: Literal["search", "open_page", "find_in_page"]
    queries: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    pattern: str = ""
    round: int = 1


class WebSearchCallItem(BaseModel):
    type: Literal["web_search_call"] = "web_search_call"
    call_id: str
    mode: Literal["quick", "agentic"]
    status: Literal["completed", "partial", "failed"]
    actions: list[SearchAction] = Field(default_factory=list)


class SearchMessageItem(BaseModel):
    type: Literal["search_message"] = "search_message"
    evidence: list[Evidence] = Field(default_factory=list)
    sufficient: bool
    missing_information: list[str] = Field(default_factory=list)


class SearchReport(BaseModel):
    question: str
    mode: Literal["quick", "agentic", "read"]
    queries: list[str]
    evidence: list[Evidence]
    sufficient: bool
    missing_information: list[str] = Field(default_factory=list)
    pipeline: list[SearchStep] = Field(default_factory=list)
    actions: list[SearchAction] = Field(default_factory=list)

    def output_items(self) -> list[dict]:
        status = "completed" if self.sufficient else ("partial" if self.evidence else "failed")
        signature = f"{self.question}|{'|'.join(self.queries)}"
        call = WebSearchCallItem(
            call_id=f"search_{sha1(signature.encode()).hexdigest()[:12]}",
            mode="quick" if self.mode == "quick" else "agentic",
            status=status,
            actions=self.actions,
        )
        message = SearchMessageItem(
            evidence=self.evidence,
            sufficient=self.sufficient,
            missing_information=self.missing_information,
        )
        return [call.model_dump(), message.model_dump()]

    def tool_payload(self) -> dict:
        return {
            "question": self.question,
            "mode": self.mode,
            "queries": self.queries,
            "output_items": self.output_items(),
            "trace": {"pipeline": [step.model_dump() for step in self.pipeline]},
        }
