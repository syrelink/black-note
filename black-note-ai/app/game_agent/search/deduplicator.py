from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.game_agent.search.models import SearchResult


TRACKING_KEYS = {"spm", "from", "source", "utm_source", "utm_medium", "utm_campaign", "utm_content"}


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in TRACKING_KEYS])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    unique = []
    seen_urls = set()
    seen_titles = set()
    for result in results:
        url_key = canonical_url(result.url)
        title_key = "".join(result.title.lower().split())
        if not url_key or url_key in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(result)
    return unique
