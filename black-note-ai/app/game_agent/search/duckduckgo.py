from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.game_agent.search.models import SearchResult

# 负责删除 HTML 标签和多余空格。
def plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


class DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._current: dict | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "snippet": "", "url": self._clean_url(attributes.get("href", ""))}
            self._capture = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag: str):
        if tag == "a" and self._capture == "title":
            self._capture = None
        elif self._current is not None and self._capture == "snippet" and tag in {"a", "div"}:
            self.results.append(self._current)
            self._current = None
            self._capture = None

    def handle_data(self, data: str):
        if self._current is not None and self._capture:
            self._current[self._capture] += data.strip() + " "

    @staticmethod
    def _clean_url(url: str) -> str:
        parsed = urlparse(url)
        redirected = parse_qs(parsed.query).get("uddg")
        return unquote(redirected[0]) if redirected else url


class DuckDuckGoSearch:
    endpoint = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout_seconds: float = 6):
        self.timeout_seconds = timeout_seconds

    async def search(
        self,
        query: str,
        limit: int = 5,
        freshness_days: int | None = None,
    ) -> list[SearchResult]:
        params = {"q": query}
        time_filter = self._time_filter(freshness_days)
        if time_filter:
            params["df"] = time_filter
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = await client.get(self.endpoint, params=params, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        parser = DuckDuckGoParser()
        parser.feed(response.text)
        results = []
        for rank, item in enumerate(parser.results[: max(1, min(limit, 10))], start=1):
            url = item["url"]
            results.append(SearchResult(
                title=plain_text(item["title"]),
                snippet=plain_text(item["snippet"]),
                url=url,
                query=query,
                source_domain=urlparse(url).netloc.lower(),
                rank=rank,
            ))
        return results

    @staticmethod
    def _time_filter(days: int | None) -> str | None:
        if days is None:
            return None
        if days <= 1:
            return "d"
        if days <= 7:
            return "w"
        if days <= 31:
            return "m"
        return "y"


_DuckDuckGoParser = DuckDuckGoParser
