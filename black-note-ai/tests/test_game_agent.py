"""最小冒烟测试：覆盖无 LangGraph 版本中不依赖模型与数据库的纯逻辑。"""

from __future__ import annotations

from app.game_agent.memory import (
    context_summary_from_state,
    split_by_recent_budget,
    split_into_complete_turns,
)
from app.game_agent.search import plain_text
from app.game_agent.skills import SkillRegistry
from app.game_agent.tools import read_skill_reference, skill


def test_skill_registry_catalog_and_load():
    registry = SkillRegistry.default()
    catalog = registry.catalog()
    names = {item.name for item in catalog}
    assert {"game-news", "gameplay-guide", "game-build-advisor"} <= names
    for item in catalog:
        assert item.description  # 目录层必须有一句话描述
    doc = registry.load("game-news")
    assert doc.name == "game-news"
    assert "工作流" in doc.content


def test_skill_tool_returns_content():
    result = skill.invoke({"name": "game-news"})
    assert '"status": "loaded"' in result
    assert "game-news" in result


def test_read_skill_reference_rejects_unknown():
    result = read_skill_reference.invoke({"name": "game-news", "path": "references/nope.md"})
    assert '"error"' in result


def test_plain_text_strips_html():
    assert plain_text("<b>hello</b>   world") == "hello world"


def test_split_into_complete_turns():
    from langchain_core.messages import AIMessage, HumanMessage
    messages = [
        HumanMessage(content="q1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
    ]
    turns = split_into_complete_turns(messages)
    assert len(turns) == 2
    assert len(turns[0]) == 2


def test_split_by_recent_budget_keeps_recent():
    from langchain_core.messages import AIMessage, HumanMessage
    messages = []
    for i in range(10):
        messages.append(HumanMessage(content=f"q{i}"))
        messages.append(AIMessage(content=f"a{i}"))
    expired, recent = split_by_recent_budget(messages, recent_budget=50)
    assert len(recent) >= 2
    assert len(expired) + len(recent) == len(messages)


def test_context_summary_from_state_empty():
    assert context_summary_from_state({}) is not None
