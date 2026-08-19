import asyncio
import json
from pathlib import Path

import pytest
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.attachment_store import MinioAttachmentStore
from app.game_agent.attachments import (
    AttachmentArtifactService,
    decode_data_url,
    extract_file_text,
    hydrate_current_images,
)
from app.game_agent.memory import (
    ContextBudget,
    ContextManager,
    context_summary_from_state,
    record_token_observation,
    split_by_balanced_units,
    split_by_recent_budget,
    split_into_complete_turns,
    sync_token_ledger,
)
from app.game_agent.models import AttachmentInput, AttachmentRef, ChatRequest, ContextSummary, HarnessState
from app.main import _restore_legacy_attachment_urls, _user_message
from app.game_agent.search.deduplicator import deduplicate_results
from app.game_agent.search.extractor import extract_page, relevant_passages
from app.game_agent.search.fetcher import is_safe_public_url
from app.game_agent.search.models import Evidence, SearchAction, SearchReport, SearchResult, SearchStep
from app.game_agent.search.query_rewriter import plan_queries, rewrite_queries
from app.game_agent.search.service import GameSearchService
from app.game_agent.tools import (
    AGENT_TOOLS,
    _DuckDuckGoParser,
    read_skill_reference,
    skill,
    skill_registry,
    web_search,
)
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


def test_legacy_game_summary_migrates_to_context_summary():
    summary = context_summary_from_state({
        "running_summary": {
            "active_goal": "帮助用户规划下一步",
            "resolved_games": ["艾尔登法环"],
            "resolved_entities": ["摩恩城"],
            "user_preferences": ["不要剧透"],
            "confirmed_facts": ["用户位于啜泣半岛"],
            "important_tool_results": ["攻略建议先完成送信任务"],
            "unresolved_questions": ["是否已经见过伊蕾娜"],
            "attachment_refs": ["screen-1"],
        }
    })
    assert summary.primary_request_and_intent == ["帮助用户规划下一步"]
    assert "已识别游戏：艾尔登法环" in summary.critical_context
    assert summary.pending_tasks == ["是否已经见过伊蕾娜"]
    assert summary.referenced_artifacts == ["screen-1"]


def test_persisted_user_message_contains_only_attachment_reference():
    request = ChatRequest(
        question="这是什么角色？",
        attachments=[AttachmentInput(
            name="role.png",
            mime_type="image/png",
            size=3,
            data_url="data:image/png;base64,QUJD",
        )],
    )
    ref = AttachmentRef(
        attachment_id="img-1",
        name="role.png",
        mime_type="image/png",
        size=3,
    )
    message = _user_message(request, [ref])
    assert message.content[0] == {"type": "text", "text": "这是什么角色？"}
    assert "role.png" in message.content[1]["text"]
    assert "attachment://img-1" in message.content[1]["text"]
    assert "base64" not in json.dumps(message.content)


def test_current_image_is_hydrated_only_in_ephemeral_model_context():
    persisted = HumanMessage(content=[
        {"type": "text", "text": "分析图片"},
        {"type": "text", "text": "attachment://img-1"},
    ], id="h1")

    async def loader(attachment_id: str, session_id: str):
        assert (attachment_id, session_id) == ("img-1", "session-1")
        return {"mime_type": "image/png", "content": b"ABC"}

    hydrated = asyncio.run(hydrate_current_images(
        [persisted],
        [{
            "attachment_id": "img-1",
            "name": "role.png",
            "mime_type": "image/png",
            "size": 3,
        }],
        session_id="session-1",
        loader=loader,
    ))
    assert len(persisted.content) == 2
    assert hydrated[0].content[-1]["type"] == "image_url"
    assert hydrated[0].content[-1]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_minio_attachment_store_wraps_blocking_client():
    calls = []

    class Response:
        def read(self):
            return b"ABC"

        def close(self):
            calls.append("close")

        def release_conn(self):
            calls.append("release")

    class Client:
        def bucket_exists(self, bucket):
            calls.append(("exists", bucket))
            return False

        def make_bucket(self, bucket):
            calls.append(("make", bucket))

        def put_object(self, bucket, key, stream, size, content_type):
            calls.append(("put", bucket, key, stream.read(), size, content_type))

        def get_object(self, bucket, key):
            calls.append(("get", bucket, key))
            return Response()

        def remove_object(self, bucket, key):
            calls.append(("delete", bucket, key))

    store = MinioAttachmentStore("127.0.0.1:9000", "key", "secret", "images")
    store.client = Client()
    asyncio.run(store.setup())
    asyncio.run(store.put("sessions/a/img-1", b"ABC", "image/png"))
    assert asyncio.run(store.get("sessions/a/img-1")) == b"ABC"
    asyncio.run(store.delete_many(["sessions/a/img-1"]))
    assert ("make", "images") in calls
    assert ("put", "images", "sessions/a/img-1", b"ABC", 3, "image/png") in calls
    assert ("delete", "images", "sessions/a/img-1") in calls


def test_model_sees_skill_reference_and_search_tools():
    assert AGENT_TOOLS == [skill, read_skill_reference, web_search]
    schema = web_search.args_schema.model_json_schema()
    assert set(schema["properties"]) == {"query", "depth"}
    assert set(skill.args_schema.model_json_schema()["properties"]) == {"name"}
    assert set(read_skill_reference.args_schema.model_json_schema()["properties"]) == {
        "name", "path",
    }


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


def test_skill_tool_returns_full_body_in_tool_result():
    payload = json.loads(skill.invoke({"name": "game-news"}))
    assert payload["status"] == "loaded"
    assert payload["output_items"][0]["type"] == "skill_load"
    assert "# Game News" in payload["content"]


def test_skill_reference_is_loaded_by_a_separate_tool():
    payload = json.loads(read_skill_reference.invoke({
        "name": "game-news",
        "path": "references/source-policy.md",
    }))
    assert payload["resource"] == "references/source-policy.md"
    assert payload["content"]


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


def test_expired_image_and_text_enter_one_multimodal_compaction_call(monkeypatch):
    image = "data:image/png;base64,QUJD"
    captured_messages = []

    async def capture_summary(model, schema, messages, max_tokens=None):
        captured_messages.extend(messages)
        return ContextSummary(
            key_concepts=["艾尔登法环"],
            critical_context=["旧图片展示角色装备界面"],
        )

    monkeypatch.setattr("app.game_agent.memory.invoke_validated_json", capture_summary)
    manager = ContextManager(
        summary_model=object(),
        budget=budget(recent_tokens=1, summary_tokens=500),
    )
    current = HumanMessage(content=[
        {"type": "text", "text": "分析图片"},
        {"type": "image_url", "image_url": {"url": image}},
    ], id="current")
    unchanged = asyncio.run(manager.compact({"messages": [current]}, force=True))
    assert unchanged["compacted"] is False
    assert captured_messages == []

    messages = [current, AIMessage(content="旧回答", id="a1"), HumanMessage(content="继续", id="h2")]
    compacted = asyncio.run(manager.compact({"messages": messages}, force=True))
    assert compacted["compacted"] is True
    multimodal = next(message for message in captured_messages if message.id == "current")
    assert multimodal.content[0] == {"type": "text", "text": "分析图片"}
    assert multimodal.content[1]["image_url"]["url"] == image
    assert compacted["context_summary"]["key_concepts"] == ["艾尔登法环"]
    assert image not in json.dumps(compacted["context_summary"], ensure_ascii=False)


def test_image_data_is_not_given_a_fixed_local_token_price(monkeypatch):
    monkeypatch.setattr("app.game_agent.memory.count_tokens_approximately", lambda messages: 7)
    first = HumanMessage(content=[
        {"type": "text", "text": "分析图片"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
    ])
    second = first.model_copy(update={
        "content": [
            *first.content,
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,REVG"}},
        ]
    })
    from app.game_agent.memory import message_tokens
    assert message_tokens([first]) == 7
    assert message_tokens([second]) == 7


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


def test_provider_usage_is_recorded_without_changing_runtime_estimate():
    ledger = sync_token_ledger([HumanMessage(content="测试", id="h1")])
    previous = ledger.protocol_overhead_tokens
    observed = record_token_observation(ledger.model_dump(), 100, 500)
    assert observed.last_estimated_prompt_tokens == 100
    assert observed.last_actual_prompt_tokens == 500
    assert observed.protocol_overhead_tokens == previous


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
        "context/pressure",
        "compaction/start",
        "compaction/summary",
        "compaction/end",
    ]
    metrics = update["context_metrics"]
    assert metrics["tokens_before_compaction"] > metrics["tokens_after_compaction"]
    assert metrics["reduced_tokens"] > 0
    assert metrics["compacted_message_ids"] == ["h1", "a1"]
    assert metrics["retained_message_ids"] == ["h2"]


def test_context_pressure_is_logged_even_when_compaction_is_not_needed():
    events = []
    manager = ContextManager(
        summary_model=None,
        budget=budget(context_window_tokens=10000, trigger_ratio=0.8),
    )
    update = asyncio.run(manager.compact({
        "messages": [HumanMessage(content="short", id="h1")],
    }, emit=events.append))
    assert update["compacted"] is False
    assert [event["event_type"] for event in events] == ["context/pressure"]
    assert events[0]["source"] == "local_estimate"
    assert events[0]["will_compact"] is False


def test_summary_timeout_falls_back_without_blocking(monkeypatch):
    async def slow_summary(*args, **kwargs):
        await asyncio.sleep(0.1)
        return ContextSummary(current_work=["should not finish"])

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
    assert "old context" in json.dumps(update["context_summary"]["critical_context"])


def test_deterministic_summary_reducer_honors_budget():
    manager = ContextManager(summary_model=None, budget=budget(summary_tokens=50))
    summary = ContextSummary(
        primary_request_and_intent=["x" * 100],
        critical_context=["fact" * 40 for _ in range(20)],
        important_tool_results=["result" * 50 for _ in range(20)],
        current_work=["n" * 500 for _ in range(10)],
    )
    reduced = manager._deterministic_reduce(summary)
    minimum_schema_tokens = manager._summary_tokens(ContextSummary())
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


def test_text_attachment_is_extracted_without_persisting_raw_data():
    import base64

    raw = "玛莲妮亚是艾尔登法环角色".encode()
    data_url = "data:text/plain;base64," + base64.b64encode(raw).decode()
    assert decode_data_url(data_url, len(raw)) == raw
    assert extract_file_text("notes.txt", "text/plain", raw) == raw.decode()
    artifact = asyncio.run(AttachmentArtifactService().analyze({
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
