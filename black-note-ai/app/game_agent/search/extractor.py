from __future__ import annotations

import re
from html.parser import HTMLParser

from app.game_agent.search.models import FetchedPage


class PageTextParser(HTMLParser):
    ignored_tags = {"script", "style", "svg", "noscript", "nav", "footer", "header", "form"}
    block_tags = {"p", "article", "section", "main", "h1", "h2", "h3", "li", "blockquote"}

    def __init__(self):
        super().__init__()
        self.title = ""
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs):
        if tag in self.ignored_tags:
            self._ignored_depth += 1
        if tag == "title":
            self._capture_title = True
        if tag in self.block_tags and self._ignored_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag == "title":
            self._capture_title = False
        if tag in self.ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        if tag in self.block_tags and self._ignored_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self.title += text + " "
        self.parts.append(text + " ")


def extract_page(html: str, url: str, fallback_title: str = "") -> FetchedPage:
    parser = PageTextParser()
    parser.feed(html)
    lines = []
    for line in "".join(parser.parts).splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if len(normalized) >= 20 and normalized not in lines:
            lines.append(normalized)
    return FetchedPage(
        url=url,
        title=parser.title.strip() or fallback_title,
        text="\n".join(lines)[:60000],
    )


def relevant_passages(text: str, terms: set[str], limit: int = 3) -> list[str]:
    candidates = [line.strip() for line in text.splitlines() if len(line.strip()) >= 20]
    scored = []
    for index, passage in enumerate(candidates):
        lowered = passage.lower()
        score = sum(1 for term in terms if term and term in lowered)
        if score:
            scored.append((score, -index, passage[:700]))
    scored.sort(reverse=True)
    return [passage for _, _, passage in scored[:limit]]
