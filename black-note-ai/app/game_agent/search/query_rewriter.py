from __future__ import annotations

import asyncio
import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.game_agent.search.models import Evidence, SearchPlan
from app.game_agent.structured import invoke_validated_json


PLANNER_PROMPT = """你是 GameRover Agentic Search 的查询规划器。
根据用户问题、已执行查询、已有证据和缺失信息，动态生成下一轮 1～4 个互补搜索 Query。

要求：
1. Query 必须直接服务于尚未解决的信息缺口，禁止仅机械追加 wiki、攻略、official 等固定后缀。
2. 已有证据足以覆盖的方向不要重复搜索；不要返回已经执行过的 Query。
3. 时效问题包含版本、日期或公告意图；角色机制、配队和攻略使用玩家实际可能发布内容的表述。
4. 优先生成信息密度高、搜索引擎可理解的短 Query，可以中英文混合，但不要生成同义重复项。
5. preferred_sources 只填写真正需要的来源类别，例如 official、wiki、news、community。
"""


async def plan_queries(
    *,
    model: BaseChatModel | None,
    game: str,
    question: str,
    intent: str,
    previous_queries: list[str],
    evidence: list[Evidence],
    missing_information: list[str],
    max_queries: int = 3,
) -> SearchPlan:
    if model is not None:
        evidence_digest = [
            {"title": item.title, "source_type": item.source_type, "snippet": item.snippet[:220]}
            for item in evidence[:6]
        ]
        payload = {
            "game": game,
            "question": question,
            "intent_hint": intent,
            "previous_queries": previous_queries,
            "evidence": evidence_digest,
            "missing_information": missing_information,
            "max_queries": max_queries,
        }
        try:
            plan = await asyncio.wait_for(
                invoke_validated_json(
                    model,
                    SearchPlan,
                    [SystemMessage(content=PLANNER_PROMPT), HumanMessage(content=json.dumps(payload, ensure_ascii=False))],
                ),
                timeout=float(os.getenv("GAME_SEARCH_PLANNER_TIMEOUT_SECONDS", "8")),
            )
            plan.queries = _unique_new(plan.queries, previous_queries, max_queries)
            if plan.queries:
                return plan
        except Exception:
            pass
    return fallback_plan(game, question, intent, previous_queries, missing_information, max_queries)


def fallback_plan(
    game: str,
    question: str,
    intent: str,
    previous_queries: list[str] | None = None,
    missing_information: list[str] | None = None,
    max_queries: int = 3,
) -> SearchPlan:
    subject = " ".join(part for part in [game.strip(), question.strip()] if part)
    missing = " ".join(missing_information or [])
    if previous_queries:
        candidates = [
            f"{subject} {missing}".strip(),
            f"{subject} 官方数据 玩家实测" if intent != "news" else f"{subject} 官方公告 更新时间",
        ]
    elif intent == "news":
        candidates = [subject, f"{subject} 官方公告", f"{subject} patch notes update"]
    elif any(word in question for word in ("对比", "区别", "哪个好", "还是")):
        candidates = [subject, f"{subject} 数据对比", f"{subject} 玩家实测"]
    elif any(word in question for word in ("配队", "攻略", "怎么打", "培养", "开荒")):
        candidates = [subject, f"{subject} 机制 配置", f"{subject} 实战攻略"]
    else:
        candidates = [subject, f"{subject} 资料 设定"]
    queries = _unique_new(candidates, previous_queries or [], max_queries)
    return SearchPlan(
        intent="news" if intent == "news" else "research",
        queries=queries or [subject],
        rationale="规则降级规划",
    )


def rewrite_queries(game: str, question: str, intent: str, max_queries: int = 5) -> list[str]:
    """Compatibility wrapper for deterministic tests and offline fallback."""
    return fallback_plan(game, question, intent, max_queries=max_queries).queries


def _unique_new(candidates: list[str], previous: list[str], limit: int) -> list[str]:
    seen = {" ".join(item.lower().split()) for item in previous}
    result = []
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.lower()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result[:limit]
