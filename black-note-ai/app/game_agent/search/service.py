from __future__ import annotations

import asyncio
from hashlib import sha1

from langchain_core.language_models.chat_models import BaseChatModel

from app.game_agent.search.backend import SearchBackend
from app.game_agent.search.classifier import classify_source
from app.game_agent.search.deduplicator import deduplicate_results
from app.game_agent.search.extractor import relevant_passages
from app.game_agent.search.fetcher import fetch_pages
from app.game_agent.search.models import Evidence, SearchAction, SearchReport, SearchStep
from app.game_agent.search.query_rewriter import plan_queries
from app.game_agent.search.reranker import query_terms, rerank_evidence
from app.game_agent.search.sufficiency import check_evidence_sufficiency


class GameSearchService:
    def __init__(self, backend: SearchBackend, planner_model: BaseChatModel | None = None):
        self.backend = backend
        self.planner_model = planner_model

    def set_planner_model(self, model: BaseChatModel) -> None:
        self.planner_model = model

    async def quick_search(
        self,
        *,
        query: str,
        freshness_days: int | None = None,
        max_sources: int = 5,
    ) -> SearchReport:
        pipeline = [SearchStep(name="plan", label="快速搜索", detail="单 Query · 不抓取网页正文")]
        try:
            results = await self.backend.search(query, limit=max_sources + 2, freshness_days=freshness_days)
            search_status = "success"
        except Exception as exc:
            results = []
            search_status = "error"
            pipeline.append(SearchStep(name="search", label="DuckDuckGo 搜索", status="error", detail=str(exc)))
        if search_status == "success":
            pipeline.append(SearchStep(name="search", label="DuckDuckGo 搜索", detail=f"获得 {len(results)} 条候选"))

        for result in results:
            result.source_type = classify_source(result.url)
        unique = deduplicate_results(results)[:max_sources]
        evidence = [
            Evidence(
                evidence_id=sha1(result.url.encode()).hexdigest()[:12],
                title=result.title,
                url=result.url,
                source_domain=result.source_domain,
                source_type=result.source_type,
                query=query,
                snippet=result.snippet,
            )
            for result in unique
        ]
        evidence = rerank_evidence(evidence, query, max_sources)
        pipeline.append(SearchStep(name="result", label="整理顶部结果", status="success" if evidence else "partial", detail=f"返回 {len(evidence)} 条摘要证据"))
        return SearchReport(
            question=query,
            mode="quick",
            queries=[query],
            evidence=evidence,
            sufficient=bool(evidence),
            missing_information=[] if evidence else ["搜索引擎未返回可用结果"],
            pipeline=pipeline,
            actions=[SearchAction(type="search", queries=[query])],
        )

    async def research(
        self,
        *,
        game: str,
        question: str,
        intent: str = "reference",
        freshness_days: int | None = None,
        max_sources: int = 8,
        max_rounds: int = 2,
    ) -> SearchReport:
        pipeline: list[SearchStep] = []
        actions: list[SearchAction] = []
        executed_queries: list[str] = []
        accumulated_results = []
        page_cache = {}
        evidence: list[Evidence] = []
        missing: list[str] = []
        sufficient = False

        for round_number in range(1, max(1, min(max_rounds, 3)) + 1):
            plan = await plan_queries(
                model=self.planner_model,
                game=game,
                question=question,
                intent=intent,
                previous_queries=executed_queries,
                evidence=evidence,
                missing_information=missing,
                max_queries=3 if round_number == 1 else 2,
            )
            new_queries = [query for query in plan.queries if query not in executed_queries]
            if not new_queries:
                pipeline.append(SearchStep(name="stop", label=f"第 {round_number} 轮停止", status="partial", detail="规划器未生成新的有效 Query"))
                break
            executed_queries.extend(new_queries)
            pipeline.append(SearchStep(
                name="plan",
                label=f"第 {round_number} 轮动态规划",
                detail=f"{plan.intent} · {plan.rationale or '根据当前证据规划'}",
            ))
            pipeline.append(SearchStep(name="rewrite", label="生成新 Query", detail="\n".join(new_queries)))
            actions.append(SearchAction(type="search", queries=new_queries, round=round_number))

            effective_freshness = freshness_days if freshness_days is not None else plan.freshness_days
            batches = await asyncio.gather(
                *(self.backend.search(query, limit=6, freshness_days=effective_freshness) for query in new_queries),
                return_exceptions=True,
            )
            failures = 0
            round_results = []
            for batch in batches:
                if isinstance(batch, Exception):
                    failures += 1
                else:
                    round_results.extend(batch)
            accumulated_results.extend(round_results)
            pipeline.append(SearchStep(
                name="search",
                label="DuckDuckGo 并行搜索",
                status="partial" if failures else "success",
                detail=f"本轮 {len(round_results)} 条候选 · {failures} 个 Query 失败",
            ))

            for result in accumulated_results:
                result.source_type = classify_source(result.url)
            deduplicated = deduplicate_results(accumulated_results)
            pipeline.append(SearchStep(name="deduplicate", label="跨轮 URL 与标题去重", detail=f"{len(accumulated_results)} → {len(deduplicated)}"))

            fetch_candidates = self._rank_search_results(deduplicated, game, question)[: max(max_sources, 6)]
            uncached = [result for result in fetch_candidates if result.url.rstrip("/") not in page_cache]
            if uncached:
                fetched = await fetch_pages(uncached)
                page_cache.update({page.url.rstrip("/"): page for page in fetched})
                actions.append(SearchAction(type="open_page", urls=[item.url for item in uncached], round=round_number))
            successful_pages = sum(1 for result in fetch_candidates if (page := page_cache.get(result.url.rstrip("/"))) and not page.error and page.text)
            pipeline.append(SearchStep(
                name="fetch",
                label="按需打开新网页",
                status="partial" if successful_pages < len(fetch_candidates) else "success",
                detail=f"缓存命中后可用 {successful_pages} / {len(fetch_candidates)}",
            ))

            terms = query_terms(f"{game} {question}")
            evidence = self._build_evidence(fetch_candidates, page_cache, terms)
            evidence = rerank_evidence(evidence, f"{game} {question}", max_sources)
            actions.append(SearchAction(type="find_in_page", urls=[item.url for item in evidence], pattern=question, round=round_number))
            pipeline.append(SearchStep(name="rerank", label="提取段落并重排证据", detail=f"保留 {len(evidence)} 条证据"))

            sufficient, missing = check_evidence_sufficiency(evidence)
            pipeline.append(SearchStep(
                name="sufficiency",
                label="检查证据充分性",
                status="success" if sufficient else "partial",
                detail="证据充足，停止搜索" if sufficient else "；".join(missing),
            ))
            if sufficient:
                break

        return SearchReport(
            question=question,
            mode="agentic",
            queries=executed_queries,
            evidence=evidence,
            sufficient=sufficient,
            missing_information=missing,
            pipeline=pipeline,
            actions=actions,
        )

    @staticmethod
    def _build_evidence(results, page_cache, terms: set[str]) -> list[Evidence]:
        evidence = []
        for result in results:
            page = page_cache.get(result.url.rstrip("/"))
            passages = relevant_passages(page.text, terms) if page and not page.error else []
            evidence.append(Evidence(
                evidence_id=sha1(result.url.encode()).hexdigest()[:12],
                title=(page.title if page and page.title else result.title),
                url=result.url,
                source_domain=result.source_domain,
                source_type=result.source_type,
                query=result.query,
                snippet=result.snippet,
                relevant_passages=passages,
                published_at=page.published_at if page else None,
            ))
        return evidence

    @staticmethod
    def _rank_search_results(results, game: str, question: str):
        terms = query_terms(f"{game} {question}")
        source_weight = {"official": 5, "wiki": 4, "news": 3, "web": 2, "community": 1}
        return sorted(
            results,
            key=lambda result: (
                sum(term in f"{result.title} {result.snippet}".lower() for term in terms) * 2
                + source_weight.get(result.source_type, 0)
                - result.rank * 0.05
            ),
            reverse=True,
        )
