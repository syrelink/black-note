from __future__ import annotations

import re

from app.game_agent.search.models import Evidence


SOURCE_WEIGHTS = {"official": 4.0, "wiki": 3.0, "news": 2.0, "web": 1.0, "community": 0.5}


def query_terms(value: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", value) if len(term) >= 2}


def score_evidence(evidence: Evidence, question: str) -> float:
    terms = query_terms(question)
    haystack = " ".join([evidence.title, evidence.snippet, *evidence.relevant_passages]).lower()
    overlap = sum(1 for term in terms if term in haystack)
    passage_bonus = min(len(evidence.relevant_passages), 3) * 0.8
    return round(overlap * 1.5 + SOURCE_WEIGHTS.get(evidence.source_type, 0) + passage_bonus, 2)


def rerank_evidence(evidence: list[Evidence], question: str, limit: int) -> list[Evidence]:
    for item in evidence:
        item.relevance_score = score_evidence(item, question)
    return sorted(evidence, key=lambda item: item.relevance_score, reverse=True)[:limit]
