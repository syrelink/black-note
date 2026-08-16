from __future__ import annotations

from urllib.parse import urlparse


OFFICIAL_HINTS = ("official", "bandainamco", "playstation.com", "xbox.com", "steampowered.com", "hoyoverse.com", "hypergryph.com")
WIKI_HINTS = ("wiki", "fandom.com", "biligame.com", "moegirl.org")
COMMUNITY_HINTS = ("reddit.com", "tieba.baidu.com", "zhihu.com", "nga.cn", "bilibili.com")
NEWS_HINTS = ("news", "ign.com", "gamespot.com", "gamersky.com", "3dmgame.com", "ali213.net")


def classify_source(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if any(hint in domain for hint in OFFICIAL_HINTS):
        return "official"
    if any(hint in domain for hint in WIKI_HINTS):
        return "wiki"
    if any(hint in domain for hint in NEWS_HINTS):
        return "news"
    if any(hint in domain for hint in COMMUNITY_HINTS):
        return "community"
    return "web"
