"""提供给主 Agent 的 Tool Calling 接口。

本文件只定义模型可见的工具名称、参数和用途。Skill 以文档形式按需加载；
网页搜索直接调用最小化的 DuckDuckGo 实现。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from langchain.tools import tool

from app.game_agent.search import DuckDuckGoSearch
from app.game_agent.skills import SkillRegistry


skill_registry = SkillRegistry(
    Path(os.getenv("GAME_SKILLS_DIR", Path(__file__).resolve().parent / "skills"))
)

search_backend = DuckDuckGoSearch()


@tool
def skill(name: str) -> str:
    """按名称加载一个 Skill；返回完整 SKILL.md，供下一次 Agent Step 按其中流程执行。"""
    try:
        document = skill_registry.load(name.strip())
    except Exception as exc:
        return json.dumps({
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "tool": "skill",
        }, ensure_ascii=False)
    return json.dumps({
        "status": "loaded",
        "skill": document.name,
        "content": document.content,
    }, ensure_ascii=False)


@tool
def read_skill_reference(name: str, path: str) -> str:
    """读取 Skill 明确引用的 references/*.md；只有 SKILL.md 要求且任务需要时才调用。"""
    try:
        document = skill_registry.load(name.strip(), path.strip())
    except Exception as exc:
        return json.dumps({
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "tool": "read_skill_reference",
        }, ensure_ascii=False)
    return json.dumps({
        "status": "loaded",
        "skill": document.name,
        "resource": document.resource,
        "content": document.content,
    }, ensure_ascii=False)


@tool
async def web_search(query: str) -> str:
    """搜索公开网页。query 应是根据当前文字、图片和对话生成的完整检索问题；返回标题、摘要与链接。"""
    search_query = query.strip()
    if not search_query:
        return json.dumps({"error": "query 不能为空", "error_type": "ValueError"}, ensure_ascii=False)
    try:
        results = await search_backend.search(search_query, limit=5)
    except Exception as exc:
        return json.dumps({
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "tool": "web_search",
        }, ensure_ascii=False)
    if not results:
        return json.dumps({"query": search_query, "results": [], "note": "未找到结果"}, ensure_ascii=False)
    return json.dumps({
        "query": search_query,
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet, "domain": r.source_domain}
            for r in results
        ],
    }, ensure_ascii=False)


# 只有列表中的函数会通过 model.bind_tools 暴露给主 Agent。
AGENT_TOOLS = [skill, read_skill_reference, web_search]
