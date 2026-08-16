from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

import httpx

from app.game_agent.search.extractor import extract_page
from app.game_agent.search.models import FetchedPage, SearchResult


def is_safe_public_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
        return not (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved)
    except ValueError:
        return True


async def fetch_pages(
    results: list[SearchResult],
    concurrency: int = 8,
    timeout_seconds: float = 6,
) -> list[FetchedPage]:
    semaphore = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True, limits=limits) as client:
        async def fetch(result: SearchResult) -> FetchedPage:
            if not is_safe_public_url(result.url):
                return FetchedPage(url=result.url, title=result.title, error="unsafe URL")
            try:
                async with semaphore:
                    response = await client.get(result.url, headers={"User-Agent": "Mozilla/5.0 Game_Rover/1.0"})
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return FetchedPage(url=result.url, title=result.title, error=f"unsupported content type: {content_type}")
                if len(response.content) > 3_000_000:
                    return FetchedPage(url=result.url, title=result.title, error="page too large")
                page = extract_page(response.text, result.url, result.title)
                return page
            except Exception as exc:
                return FetchedPage(url=result.url, title=result.title, error=str(exc))

        return await asyncio.gather(*(fetch(result) for result in results))
