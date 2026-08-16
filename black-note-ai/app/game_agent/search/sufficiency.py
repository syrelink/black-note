from __future__ import annotations

from app.game_agent.search.models import Evidence


def check_evidence_sufficiency(evidence: list[Evidence]) -> tuple[bool, list[str]]:
    useful = [item for item in evidence if item.relevance_score > 1 and (item.relevant_passages or item.snippet)]
    domains = {item.source_domain for item in useful}
    if len(useful) >= 2 and len(domains) >= 2:
        return True, []
    missing = []
    if len(useful) < 2:
        missing.append("至少需要两条与问题直接相关的证据")
    if len(domains) < 2:
        missing.append("缺少不同来源之间的交叉验证")
    return False, missing
