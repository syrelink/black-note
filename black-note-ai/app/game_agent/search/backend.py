from __future__ import annotations

from typing import Protocol

from app.game_agent.search.models import SearchResult


class SearchBackend(Protocol):
    async def search(
        self,
        query: str,
        limit: int = 5,
        freshness_days: int | None = None,
    ) -> list[SearchResult]: ...
