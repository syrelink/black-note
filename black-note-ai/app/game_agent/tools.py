"""提供给主 Agent 的 Tool Calling 接口。

本文件只定义模型可见的工具名称、参数和用途；复杂搜索实现位于 search/。
工具统一返回 JSON 字符串，使 ToolMessage、Harness 轨迹和前端展示共享同一结果。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel

from app.game_agent.search import DuckDuckGoSearch, GameSearchService
from app.game_agent.search.duckduckgo import DuckDuckGoParser, plain_text
from app.game_agent.skills import SkillRegistry


search_service = GameSearchService(DuckDuckGoSearch())
skill_registry = SkillRegistry(
    Path(os.getenv("GAME_SKILLS_DIR", Path(__file__).resolve().parent / "skills"))
)


def configure_search_planner(model: BaseChatModel) -> None:
    """让 Agentic Search 复用主模型进行动态 Query 规划和证据判断。"""
    search_service.set_planner_model(model)


def _report_json(report) -> str:
    """把内部 SearchReport 转成模型和前端约定的 Tool Payload。"""
    return json.dumps(report.tool_payload(), ensure_ascii=False)


def _error_json(question: str, mode: str, error: Exception) -> str:
    """搜索失败也返回合法 ToolMessage，避免打断 LangChain 工具协议。"""
    return json.dumps({
        "question": question,
        "mode": mode,
        "queries": [],
        "output_items": [
            {
                "type": "web_search_call",
                "call_id": "search_failed",
                "mode": mode,
                "status": "failed",
                "actions": [],
            },
            {
                "type": "search_message",
                "evidence": [],
                "sufficient": False,
                "missing_information": [str(error)],
            },
        ],
        "trace": {"pipeline": [{"name": "error", "label": "搜索失败", "status": "error", "detail": str(error)}]},
    }, ensure_ascii=False)


@tool
def load_skill(name: str, resource: str | None = None) -> str:
    """加载一个可用 Skill 的专业工作流；仅当已加载 Skill 明确要求时才传入 references/xxx.md。"""
    try:
        document = skill_registry.load(name.strip(), resource.strip() if resource else None)
    except Exception as exc:
        return json.dumps({
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "tool": "load_skill",
        }, ensure_ascii=False)
    return json.dumps({
        "status": "loaded",
        "skill": document.name,
        "resource": document.resource,
        "output_items": [{
            "type": "skill_load",
            "skill": document.name,
            "resource": document.resource,
            "status": "loaded",
        }],
    }, ensure_ascii=False)


@tool
async def web_search(query: str, depth: Literal["quick", "research"] = "quick") -> str:
    """搜索公开网页。query 应是根据当前文字、图片和对话生成的完整检索问题；简单事实与最新状态使用 quick，需要多来源阅读、比较或核验时使用 research。"""
    search_query = query.strip()
    if not search_query:
        return _error_json("", depth, ValueError("query 不能为空"))
    try:
        if depth == "research":
            report = await search_service.research(
                game="",
                question=search_query,
                intent="reference",
                max_sources=8,
                max_rounds=2,
            )
        else:
            report = await search_service.quick_search(query=search_query, max_sources=5)
        return _report_json(report)
    except Exception as exc:
        return _error_json(search_query, depth, exc)


# 兼容已有测试和旧导入路径；它们不是绑定给模型的新工具。
_plain_text = plain_text
_DuckDuckGoParser = DuckDuckGoParser

# 只有列表中的函数会通过 model.bind_tools 暴露给主 Agent。
AGENT_TOOLS = [load_skill, web_search]
