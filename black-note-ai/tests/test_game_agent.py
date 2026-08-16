import asyncio
import json
from pathlib import Path

import pytest
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.game_agent.attachments import AttachmentArtifactService, decode_data_url, extract_file_text
from app.game_agent.graph import close_tool_calls_for_force_finish
from app.game_agent.memory import (
    ContextBudget,
    ContextManager,
    calibrate_token_ledger,
    split_by_balanced_units,
    split_by_recent_budget,
    split_into_complete_turns,
    sync_token_ledger,
)
from app.game_agent.models import AttachmentInput, ChatRequest, HarnessState, RunningSummary, VisualMemory
from app.main import _restore_legacy_attachment_urls, _user_message
from app.game_agent.search.deduplicator import deduplicate_results
from app.game_agent.search.extractor import extract_page, relevant_passages
from app.game_agent.search.fetcher import is_safe_public_url
from app.game_agent.search.models import Evidence, SearchAction, SearchReport, SearchResult, SearchStep
from app.game_agent.search.query_rewriter import plan_queries, rewrite_queries
from app.game_agent.search.service import GameSearchService
from app.game_agent.tools import AGENT_TOOLS, _DuckDuckGoParser, load_skill, skill_registry, web_search
from app.game_agent.tracing import create_tool_call_wrapper, truncate_tool_payload
from app.session_store import SessionStore


def budget(**overrides) -> ContextBudget:
    values = {
        "context_window_tokens": 143,
        "trigger_ratio": 0.7,
        "recent_tokens": 10,
        "summary_tokens": 40,
        "tool_result_tokens": 10,
    }
    values.update(overrides)
    return ContextBudget(**values)


def test_turn_split_never_breaks_tool_call_and_result():
    messages = [
        HumanMessage(content="first", id="h1"),
        AIMessage(content="done", id="a1"),
        HumanMessage(content="latest", id="h2"),
        AIMessage(content="", id="a2", tool_calls=[{"id": "c1", "name": "search", "args": {}}]),
        ToolMessage(content="result", tool_call_id="c1", name="search", id="t1"),
        AIMessage(content="answer", id="a3"),
    ]
    turns = split_into_complete_turns(messages)
    assert len(turns) == 2
    expired, recent = split_by_recent_budget(messages, recent_budget=1)
    assert [message.id for message in expired] == ["h1", "a1"]
    assert [message.id for message in recent] == ["h2", "a2", "t1", "a3"]


def test_single_oversized_turn_uses_tool_safe_units():
    messages = [
        HumanMessage(content="研究这个问题", id="h1"),
        AIMessage(content="", id="a1", tool_calls=[{"id": "c1", "name": "search", "args": {}}]),
        ToolMessage(content="x" * 200, tool_call_id="c1", name="search", id="t1"),
        AIMessage(content="阶段结论", id="a2"),
    ]
    expired, recent = split_by_balanced_units(messages, recent_budget=1)
    expired_ids = {message.id for message in expired}
    recent_ids = {message.id for message in recent}
    assert ({"a1", "t1"} <= expired_ids) or ({"a1", "t1"} <= recent_ids)
    assert not ({"a1", "t1"} & expired_ids and {"a1", "t1"} & recent_ids)


def test_deepseek_style_context_defaults(monkeypatch):
    for key in (
        "GAME_EFFECTIVE_CONTEXT_TOKENS",
        "GAME_CONTEXT_TRIGGER_RATIO",
        "GAME_CONTEXT_RETAIN_RATIO",
        "GAME_RECENT_BUDGET_TOKENS",
        "GAME_SUMMARY_BUDGET_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)
    configured = ContextBudget.from_env()
    assert configured.context_window_tokens == 65536
    assert configured.trigger_ratio == 0.8
    assert configured.retain_ratio == 0.16
    assert configured.recent_tokens == int(65536 * 0.16)
    assert configured.summary_tokens == 8192


def test_image_is_part_of_current_multimodal_user_message():
    request = ChatRequest(
        question="这是什么角色？",
        attachments=[AttachmentInput(
            name="role.png",
            mime_type="image/png",
            size=3,
            data_url="data:image/png;base64,QUJD",
        )],
    )
    message = _user_message(request)
    assert message.content[0] == {"type": "text", "text": "这是什么角色？"}
    assert "role.png" in message.content[1]["text"]
    assert message.content[2]["type"] == "image_url"
    assert message.content[2]["image_url"]["url"].startswith("data:image/png;base64,")


def test_model_sees_one_skill_loader_and_one_search_tool():
    assert AGENT_TOOLS == [load_skill, web_search]
    schema = web_search.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"query", "depth"}
    assert set(load_skill.args_schema.model_json_schema()["properties"]) == {"name", "resource"}


def test_builtin_skills_follow_progressive_disclosure_contract():
    assert [item.name for item in skill_registry.catalog()] == [
        "game-build-advisor",
        "game-news",
        "gameplay-guide",
    ]
    document = skill_registry.load("gameplay-guide")
    assert "目标是结合当前画面" in document.content
    assert "图片落地规则" not in document.content
    reference = skill_registry.load("gameplay-guide", "references/image-grounding.md")
    assert "图片落地规则" in reference.content


def test_load_skill_returns_confirmation_without_persisting_instructions():
    payload = json.loads(load_skill.invoke({"name": "game-news"}))
    assert payload["status"] == "loaded"
    assert payload["output_items"][0]["type"] == "skill_load"
    assert "# Game News" not in json.dumps(payload, ensure_ascii=False)


def test_skill_registry_rejects_path_traversal():
    with pytest.raises(ValueError, match="references/"):
        skill_registry.load("game-news", "../SKILL.md")


def test_legacy_attachment_is_restored_from_checkpoint_image():
    transcript = [{
        "role": "user",
        "content": "分析图片",
        "attachments": [{"name": "old.png", "mime_type": "image/png", "size": 3}],
    }]
    state_messages = [HumanMessage(content=[
        {"type": "text", "text": "分析图片"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ])]
    restored = _restore_legacy_attachment_urls(transcript, state_messages)
    assert restored[0]["attachments"][0]["data_url"] == "data:image/png;base64,QUJD"


class RecordingImageService:
    def __init__(self):
        self.calls = 0

    async def summarize(self, image, source_message_id):
        self.calls += 1
        return VisualMemory(
            source_message_id=source_message_id,
            game="艾尔登法环",
            key_facts=["角色装备界面"],
        )


def test_current_image_is_only_summarized_when_its_turn_expires():
    image = "data:image/png;base64,QUJD"
    service = RecordingImageService()
    manager = ContextManager(
        summary_model=None,
        budget=budget(recent_tokens=1, summary_tokens=500),
        image_service=service,
    )
    current = HumanMessage(content=[
        {"type": "text", "text": "分析图片"},
        {"type": "image_url", "image_url": {"url": image}},
    ], id="current")
    unchanged = asyncio.run(manager.compact({"messages": [current]}, force=True))
    assert unchanged["compacted"] is False
    assert service.calls == 0

    messages = [current, AIMessage(content="旧回答", id="a1"), HumanMessage(content="继续", id="h2")]
    compacted = asyncio.run(manager.compact({"messages": messages}, force=True))
    assert compacted["compacted"] is True
    assert service.calls == 1
    assert "image_artifacts" not in compacted
    assert compacted["running_summary"]["visual_memories"][0]["source_message_id"] == "current"
    assert image not in json.dumps(compacted["running_summary"], ensure_ascii=False)


def test_token_ledger_only_estimates_new_messages(monkeypatch):
    calls = []

    def fake_message_tokens(messages):
        calls.append(messages[0].id)
        return 10

    monkeypatch.setattr("app.game_agent.memory.message_tokens", fake_message_tokens)
    first = [HumanMessage(content="一", id="h1"), AIMessage(content="二", id="a1")]
    ledger = sync_token_ledger(first)
    assert calls == ["h1", "a1"]
    ledger = sync_token_ledger(first, ledger.model_dump())
    assert calls == ["h1", "a1"]
    ledger = sync_token_ledger(
        [*first, HumanMessage(content="三", id="h2")], ledger.model_dump()
    )
    assert calls == ["h1", "a1", "h2"]
    assert ledger.active_message_tokens == 30
    sync_token_ledger(
        [HumanMessage(content="内容已替换", id="h1"), first[1]], ledger.model_dump()
    )
    assert calls[-1] == "h1"


def test_token_ledger_uses_api_usage_to_calibrate_overhead():
    ledger = sync_token_ledger([HumanMessage(content="测试", id="h1")])
    previous = ledger.protocol_overhead_tokens
    calibrated = calibrate_token_ledger(ledger.model_dump(), 100, 500)
    assert calibrated.last_actual_prompt_tokens == 500
    assert calibrated.protocol_overhead_tokens == round(previous * 0.7 + 400 * 0.3)


def test_harness_tracer_groups_model_and_tools_into_steps():
    from app.game_agent.tracing import HarnessTracer

    tracer = HarnessTracer("run-1", 3)
    started = tracer.record_custom({
        "kind": "harness_event",
        "event": {"event_type": "model/start", "node": "Agent"},
    })
    assert [event["event_type"] for event in started] == ["step/start", "model/start"]
    assert all(event["step_number"] == 1 for event in started)

    model_end = tracer.record_custom({
        "kind": "harness_event",
        "event": {
            "event_type": "model/end",
            "duration_ms": 120,
            "ttft_ms": 40,
            "generation_ms": 80,
            "requested_tools": ["web_search"],
        },
    })
    assert [event["event_type"] for event in model_end] == ["model/end"]
    tool_end = tracer.record_custom({
        "kind": "harness_event",
        "event": {"event_type": "tool/result", "tool_name": "web_search"},
    })
    assert tool_end[0]["step_number"] == 1

    next_step = tracer.record_custom({
        "kind": "harness_event",
        "event": {"event_type": "model/start", "node": "Agent"},
    })
    assert [event["event_type"] for event in next_step] == [
        "step/end", "step/start", "model/start",
    ]
    assert next_step[-1]["step_number"] == 2


def test_forced_compaction_replaces_old_turns_with_bounded_summary():
    messages = [
        HumanMessage(content="我常玩英雄联盟，主玩辅助。", id="h1"),
        AIMessage(content="记住了。", id="a1"),
        HumanMessage(content="最近想了解绝区零。", id="h2"),
        AIMessage(content="可以。", id="a2"),
    ]
    manager = ContextManager(summary_model=None, budget=budget(recent_tokens=1))
    update = asyncio.run(manager.compact({"messages": messages}, force=True))
    assert update["compacted"] is True
    assert {message.id for message in update["messages"]} == {"h1", "a1"}
    assert update["context_metrics"]["messages_after"] == 2


def test_context_usage_ratio_triggers_compaction_before_model_limit():
    messages = [
        HumanMessage(content="x" * 180, id="h1"),
        AIMessage(content="y" * 180, id="a1"),
        HumanMessage(content="latest", id="h2"),
        AIMessage(content="answer", id="a2"),
    ]
    manager = ContextManager(
        summary_model=None,
        budget=budget(context_window_tokens=140, trigger_ratio=0.7, recent_tokens=10),
    )
    update = asyncio.run(manager.compact({"messages": messages}))
    assert update["compacted"] is True
    assert update["context_metrics"]["trigger_tokens"] == 98
    assert update["context_metrics"]["trigger_ratio"] == 0.7


def test_compaction_records_lifecycle_and_convergence():
    events = []
    messages = [
        HumanMessage(content="x" * 400, id="h1"),
        AIMessage(content="y" * 400, id="a1"),
        HumanMessage(content="latest", id="h2"),
    ]
    manager = ContextManager(
        summary_model=None,
        budget=budget(context_window_tokens=160, trigger_ratio=0.7, recent_tokens=10),
    )
    update = asyncio.run(manager.compact({"messages": messages}, emit=events.append))
    assert [event["event_type"] for event in events] == [
        "compaction/start",
        "compaction/summary",
        "compaction/end",
    ]
    metrics = update["context_metrics"]
    assert metrics["tokens_before_compaction"] > metrics["tokens_after_compaction"]
    assert metrics["reduced_tokens"] > 0
    assert metrics["compacted_message_ids"] == ["h1", "a1"]
    assert metrics["retained_message_ids"] == ["h2"]


def test_summary_timeout_falls_back_without_blocking(monkeypatch):
    async def slow_summary(*args, **kwargs):
        await asyncio.sleep(0.1)
        return RunningSummary(active_goal="should not finish")

    monkeypatch.setenv("GAME_SUMMARY_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr("app.game_agent.memory.invoke_validated_json", slow_summary)
    manager = ContextManager(summary_model=object(), budget=budget(recent_tokens=1, summary_tokens=300))
    messages = [
        HumanMessage(content="old context", id="h1"),
        AIMessage(content="old answer", id="a1"),
        HumanMessage(content="latest", id="h2"),
    ]
    update = asyncio.run(manager.compact({"messages": messages}, force=True))
    assert update["compacted"] is True
    assert "old context" in update["running_summary"]["narrative"]


def test_deterministic_summary_reducer_honors_budget():
    manager = ContextManager(summary_model=None, budget=budget(summary_tokens=50))
    summary = RunningSummary(
        active_goal="x" * 100,
        confirmed_facts=["fact" * 40 for _ in range(20)],
        important_tool_results=["result" * 50 for _ in range(20)],
        narrative="n" * 5000,
    )
    reduced = manager._deterministic_reduce(summary)
    minimum_schema_tokens = manager._summary_tokens(RunningSummary())
    assert manager._summary_tokens(reduced) <= max(50, minimum_schema_tokens)


@tool
async def huge_tool(query: str) -> str:
    """Return a deliberately oversized result."""
    return query + "x" * 1000


def _run_tool_node(tool_node: ToolNode, call: dict) -> ToolMessage:
    builder = StateGraph(HarnessState)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    result = asyncio.run(graph.ainvoke({
        "messages": [AIMessage(content="", tool_calls=[call])]
    }))
    return result["messages"][-1]


def test_tool_node_truncates_large_results_and_records_trace():
    node = ToolNode(
        [huge_tool],
        awrap_tool_call=create_tool_call_wrapper(
            result_token_budget=10,
            default_timeout_seconds=1,
        ),
    )
    message = _run_tool_node(
        node,
        {"id": "call-1", "name": "huge_tool", "args": {"query": "game"}},
    )
    trace = message.artifact["harness_trace"]
    assert len(message.content) <= 40
    assert trace["truncated"] is True
    assert trace["status"] == "success"


@tool
async def pipeline_tool(query: str) -> str:
    """Return a search pipeline for trace validation."""
    return '{"output_items":[{"type":"web_search_call","mode":"quick","status":"completed","actions":[]},{"type":"search_message","evidence":[],"sufficient":true,"missing_information":[]}],"trace":{"pipeline":[{"name":"search","label":"并行搜索","status":"success","detail":"10 条"}]}}'


def test_tool_node_extracts_search_pipeline_steps():
    node = ToolNode(
        [pipeline_tool],
        awrap_tool_call=create_tool_call_wrapper(
            result_token_budget=1000,
            default_timeout_seconds=1,
        ),
    )
    message = _run_tool_node(
        node,
        {"id": "call-2", "name": "pipeline_tool", "args": {"query": "game"}},
    )
    trace = message.artifact["harness_trace"]
    assert trace["steps"][0]["name"] == "search"
    assert [item["type"] for item in trace["output_items"]] == ["web_search_call", "search_message"]


@tool
async def slow_search(query: str) -> str:
    """Fake tool that exceeds its Harness budget."""
    await asyncio.sleep(0.05)
    return query


def test_tool_node_reports_a_readable_timeout_error():
    node = ToolNode(
        [slow_search],
        awrap_tool_call=create_tool_call_wrapper(
            result_token_budget=100,
            default_timeout_seconds=1,
            tool_timeouts={"slow_search": 0.01},
        ),
    )
    message = _run_tool_node(
        node,
        {"id": "slow-1", "name": "slow_search", "args": {"query": "game"}},
    )
    payload = json.loads(message.content)
    assert payload["error_type"] == "tool_timeout"
    assert "Harness" in payload["error"]
    assert message.artifact["harness_trace"]["status"] == "error"


def test_force_finish_closes_every_pending_tool_call():
    pending = AIMessage(content="", tool_calls=[
        {"id": "call-a", "name": "web_search", "args": {"query": "A", "depth": "quick"}},
        {"id": "call-b", "name": "web_search", "args": {"query": "B", "depth": "research"}},
    ])
    messages, traces = close_tool_calls_for_force_finish(pending)
    assert [message.tool_call_id for message in messages] == ["call-a", "call-b"]
    assert [trace.name for trace in traces] == ["web_search", "web_search"]
    assert all(trace.status == "error" for trace in traces)


def test_text_attachment_is_extracted_without_persisting_raw_data():
    import base64

    raw = "玛莲妮亚是艾尔登法环角色".encode()
    data_url = "data:text/plain;base64," + base64.b64encode(raw).decode()
    assert decode_data_url(data_url, len(raw)) == raw
    assert extract_file_text("notes.txt", "text/plain", raw) == raw.decode()
    artifact = asyncio.run(AttachmentArtifactService(None).analyze({
        "name": "notes.txt", "mime_type": "text/plain", "size": len(raw), "data_url": data_url,
    }))
    assert artifact["summary"]["extracted_text"] == raw.decode()
    assert artifact["raw_ref"].startswith("inline-file://sha256/")
    assert data_url not in str(artifact)


def test_image_only_chat_request_is_valid_and_document_is_rejected():
    import base64

    raw = b"image"
    request = ChatRequest(attachments=[{
        "name": "screen.png",
        "mime_type": "image/png",
        "size": len(raw),
        "data_url": "data:image/png;base64," + base64.b64encode(raw).decode(),
    }])
    assert request.question == ""
    with pytest.raises(ValueError, match="只支持图片附件"):
        ChatRequest(attachments=[{
            "name": "notes.txt",
            "mime_type": "text/plain",
            "size": len(raw),
            "data_url": "data:text/plain;base64," + base64.b64encode(raw).decode(),
        }])


def test_duckduckgo_parser_extracts_result_and_real_url():
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpatch">Patch notes</a>
    <a class="result__snippet">Official game update summary</a>
    """
    parser = _DuckDuckGoParser()
    parser.feed(html)
    assert parser.results[0]["url"] == "https://example.com/patch"


def test_search_query_rewriter_builds_distinct_queries():
    queries = rewrite_queries("艾尔登法环", "玛莲妮亚是谁", "reference")
    assert 1 <= len(queries) <= 3
    assert len(queries) == len(set(queries))
    assert all("guide lore" not in query for query in queries)


class PlannerModel:
    def bind(self, **_):
        return self

    async def ainvoke(self, _):
        return AIMessage(content='{"intent":"guide","queries":["绝区零 蕾米埃尔 三异常 实战循环","绝区零 蕾米埃尔 队伍伤害测试"],"rationale":"补充操作与实测","preferred_sources":["community"],"freshness_days":null}')


def test_agentic_query_planner_uses_model_generated_queries():
    plan = asyncio.run(plan_queries(
        model=PlannerModel(),
        game="绝区零",
        question="蕾米埃尔三异常队怎么搭配",
        intent="guide",
        previous_queries=["绝区零 蕾米埃尔 配队"],
        evidence=[],
        missing_information=["缺少实战验证"],
    ))
    assert plan.rationale == "补充操作与实测"
    assert all(query not in {"绝区零 蕾米埃尔 配队"} for query in plan.queries)


def test_search_report_emits_call_and_message_output_items():
    evidence = Evidence(
        evidence_id="e1",
        title="Official",
        url="https://example.com",
        source_domain="example.com",
        source_type="official",
        query="game update",
        snippet="patch released",
    )
    report = SearchReport(
        question="game update",
        mode="quick",
        queries=["game update"],
        evidence=[evidence],
        sufficient=True,
        pipeline=[SearchStep(name="search", label="搜索", detail="1 result")],
        actions=[SearchAction(type="search", queries=["game update"])],
    )
    payload = report.tool_payload()
    assert [item["type"] for item in payload["output_items"]] == ["web_search_call", "search_message"]
    assert payload["output_items"][1]["evidence"][0]["evidence_id"] == "e1"
    assert payload["trace"]["pipeline"][0]["name"] == "search"


class RecordingSearchBackend:
    def __init__(self):
        self.calls = []

    async def search(self, query, limit=5, freshness_days=None):
        self.calls.append((query, limit, freshness_days))
        return [
            SearchResult(
                title="Official update",
                url="https://example.com/update",
                snippet="The current version is 2.0.",
                query=query,
                source_domain="example.com",
                rank=1,
            )
        ]


def test_quick_search_executes_exactly_one_query():
    backend = RecordingSearchBackend()
    report = asyncio.run(GameSearchService(backend).quick_search(query="绝区零 当前版本"))
    assert len(backend.calls) == 1
    assert report.mode == "quick"
    assert report.actions[0].type == "search"


def test_search_payload_truncation_remains_valid_json():
    evidence = Evidence(
        evidence_id="e1",
        title="Long source",
        url="https://example.com",
        source_domain="example.com",
        source_type="official",
        query="q",
        snippet="x" * 2000,
        relevant_passages=["y" * 3000],
    )
    report = SearchReport(
        question="q",
        mode="agentic",
        queries=["q"],
        evidence=[evidence],
        sufficient=True,
        actions=[SearchAction(type="search", queries=["q"])],
    )
    compact, truncated = truncate_tool_payload(
        json.dumps(report.tool_payload(), ensure_ascii=False),
        200,
    )
    assert truncated is True
    assert isinstance(json.loads(compact), dict)


def test_search_result_deduplication_removes_tracking_duplicates():
    results = [
        SearchResult(title="Patch", url="https://example.com/news?utm_source=a", query="q"),
        SearchResult(title="Patch copy", url="https://example.com/news?utm_source=b", query="q"),
    ]
    assert len(deduplicate_results(results)) == 1


def test_page_extractor_ignores_navigation_and_finds_relevant_passage():
    page = extract_page("<nav>菜单菜单菜单菜单菜单</nav><main><h1>玛莲妮亚</h1><p>玛莲妮亚是艾尔登法环中的重要角色和 Boss。</p></main>", "https://example.com")
    assert "菜单" not in page.text
    assert relevant_passages(page.text, {"玛莲妮亚"})


def test_fetcher_rejects_local_and_private_urls():
    assert is_safe_public_url("http://127.0.0.1/internal") is False
    assert is_safe_public_url("http://localhost/internal") is False
    assert is_safe_public_url("https://example.com/game") is True


def test_session_title_is_bounded_and_normalized():
    assert SessionStore._title("  绝区零   怎么配队？  ") == "绝区零 怎么配队？"
    assert len(SessionStore._title("游戏" * 30)) == 29


def test_chat_page_contains_harness_controls():
    page = Path("app/web/index.html").read_text(encoding="utf-8")
    assert "GameRover" in page
    assert "Game_Rover" not in page
    assert "welcome-mode" in page
    assert "setupVoiceInput" not in page
    assert "composer-mode" not in page
    assert "attachmentInput" in page
    assert "addSelectedAttachments" in page
    assert "voiceInput" not in page
    assert "Instant" not in page
    assert "历史会话" in page
    assert "Harness 执行轨迹" in page
    assert "/ai/chat/stream" in page
    assert "/ai/sessions" in page
    assert "renderMarkdown" in page
    assert "scheduleStreamRender" in page
    assert "requestAnimationFrame(flushStreamRender)" in page
    assert "setTimeout(flushStreamRender, 80)" not in page
    assert "markdown-table-wrap" in page
    assert "tableAlignment" in page
    assert '.markdown pre code { padding: 0; background: transparent; }' in page
    assert 'nextOrderedNumber = start + 1' in page
    assert "drawerToggle" in page
    assert "drawerReopen" in page
    assert "themeToggle" in page
    assert "beginRenameSession" in page
    assert "confirmDeleteSession" in page
    assert "deleteModal" in page
    assert "session-more" in page
    assert "window.prompt" not in page
    assert "window.confirm" not in page
    assert "renderRunHistory" in page
    assert "/runs" in page
    assert "turn-trace" in page
    assert "renderSearchPipeline" in page
    assert "renderSearchOutputItems" in page
    assert "Agent 在线" not in page
    assert "返回执行轨迹" in page
    assert "renderStateValue" in page
    assert "avatar" not in page
    assert "压缩上下文" not in page
    assert "重置会话" not in page
