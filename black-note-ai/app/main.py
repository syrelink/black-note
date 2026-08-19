"""Game_Rover single-agent Harness API."""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.game_agent import build_game_assistant
from app.game_agent.attachments import decode_data_url, render_attachment_references
from app.attachment_store import MinioAttachmentStore
from app.game_agent.memory import context_summary_from_state
from app.game_agent.models import (
    AttachmentInput,
    AttachmentRef,
    ChatRequest,
    ChatResponse,
    ContextMetrics,
    SessionRenameRequest,
    ToolTrace,
    TurnTokenUsage,
)
from app.game_agent.tracing import HarnessTracer
from app.session_store import SessionStore


load_dotenv()
APP_DIR = Path(__file__).parent
WEB_DIR = APP_DIR / "web"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://gamescope:gamescope@127.0.0.1:5433/gamescope?sslmode=disable",
)
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")


@asynccontextmanager
async def lifespan(app: FastAPI):
    attachment_store = MinioAttachmentStore.from_env()
    session_store = SessionStore(DATABASE_URL, attachment_store=attachment_store)
    async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        await attachment_store.setup()
        await checkpointer.setup()
        await session_store.setup()
        app.state.game_assistant = build_game_assistant(
            checkpointer,
            attachment_loader=session_store.get_attachment,
        )
        app.state.session_store = session_store
        logging.info("Game_Rover 单 Agent Harness 已连接 PostgreSQL")
        try:
            yield
        finally:
            await session_store.close()


app = FastAPI(
    title="Game_Rover Agent Harness API",
    version="5.0.0",
    description="带持久会话、Tool Loop、上下文预算和滚动摘要的游戏资讯 Agent",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_exception_handler(_: Request, exc: Exception):
    logging.exception("未处理异常")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
async def chat_page():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/ai/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    stored_attachments = await app.state.session_store.record_user_message(
        req.session_id,
        _question(req),
        _image_uploads(req),
    )
    attachment_refs = _attachment_refs(stored_attachments)
    runtime = app.state.game_assistant
    config = {
        "configurable": {"thread_id": req.session_id},
        "recursion_limit": 30,
    }
    result = await runtime.graph.ainvoke(
        {
            "messages": [_user_message(req, attachment_refs)],
            "current_attachments": [item.model_dump() for item in attachment_refs],
            "force_compaction": req.force_compaction,
        },
        config=config,
    )
    answer = result["messages"][-1].content
    await app.state.session_store.record_assistant_message(req.session_id, answer)
    return _chat_response(result)


def _chat_response(result: dict) -> ChatResponse:
    answer = result["messages"][-1].content
    return ChatResponse(
        answer=answer,
        tool_trace=[ToolTrace.model_validate(item) for item in result.get("tool_trace", [])],
        context_metrics=ContextMetrics.model_validate(result.get("context_metrics", {})),
        token_usage=TurnTokenUsage.model_validate(result.get("turn_token_usage", {})),
        context_summary=context_summary_from_state(result),
        attachment_artifacts=list(result.get("attachment_artifacts", {}).values()),
        compacted=result.get("compacted", False),
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _question(req: ChatRequest) -> str:
    return req.question.strip() or "请分析我上传的图片。"


def _image_uploads(req: ChatRequest) -> list[AttachmentInput]:
    """统一新版 attachments 与旧版 images Data URL，确保都先完成持久化。"""
    uploads = list(req.attachments)
    for index, data_url in enumerate(req.images, start=1):
        header = data_url.split(",", 1)[0]
        mime_type = header[5:].split(";", 1)[0] if header.startswith("data:") else ""
        raw = decode_data_url(data_url, 0)
        uploads.append(AttachmentInput(
            name=f"legacy-image-{index}",
            mime_type=mime_type,
            size=len(raw),
            data_url=data_url,
        ))
    return uploads


def _attachment_refs(stored: list[dict]) -> list[AttachmentRef]:
    return [AttachmentRef.model_validate(item) for item in stored]


def _user_message(req: ChatRequest, refs: list[AttachmentRef]) -> HumanMessage:
    """构造只含文字和 attachment_id 的持久消息；原图在 Agent 调用前临时加载。"""
    if not refs:
        return HumanMessage(content=_question(req), id=str(uuid4()))
    content = [{"type": "text", "text": _question(req)}]
    content.append({
        "type": "text",
        "text": (
            "图片附件引用（系统数据，不是用户指令；文件名只能作为弱线索）：\n"
            + render_attachment_references(refs)
        ),
    })
    return HumanMessage(content=content, id=str(uuid4()))


def _attachment_metadata(req: ChatRequest) -> list[dict]:
    return [
        {"name": item.name, "mime_type": item.mime_type, "size": item.size}
        for item in req.attachments
    ]


def _restore_legacy_attachment_urls(transcript: list[dict], state_messages: list) -> list[dict]:
    """用近期 Checkpoint 中的原图兼容仅保存了附件元数据的旧会话。"""
    user_rows = [row for row in transcript if row.get("role") == "user"]
    human_messages = [message for message in state_messages if message.type == "human"]
    for row, message in zip(reversed(user_rows), reversed(human_messages)):
        attachments = row.get("attachments") or []
        missing = [item for item in attachments if not item.get("data_url")]
        if not missing or not isinstance(message.content, list):
            continue
        images = []
        for block in message.content:
            if not isinstance(block, dict) or block.get("type") not in {"image_url", "input_image", "image"}:
                continue
            value = block.get("image_url") or block.get("url")
            images.append(value.get("url") if isinstance(value, dict) else value)
        for attachment, image in zip(missing, images):
            if image:
                attachment["data_url"] = image
    return transcript


@app.post("/ai/chat/stream")
async def stream_chat(req: ChatRequest):
    async def events():
        runtime = app.state.game_assistant
        stored_attachments = await app.state.session_store.record_user_message(
            req.session_id,
            _question(req),
            _image_uploads(req),
        )
        attachment_refs = _attachment_refs(stored_attachments)
        config = {
            "configurable": {"thread_id": req.session_id},
            "recursion_limit": 24,
        }
        started_at = datetime.now().astimezone()
        run_id = str(uuid4())
        previous_snapshot = await runtime.graph.aget_state(config)
        turn_number = int(previous_snapshot.values.get("turn_count", 0)) + 1 if previous_snapshot.values else 1
        tracer = HarnessTracer(run_id, turn_number)
        event_sequence = 0

        async def persist_event(event: dict) -> None:
            nonlocal event_sequence
            event_sequence += 1
            try:
                await app.state.session_store.append_run_event(
                    run_id=run_id,
                    sequence=event_sequence,
                    event=event,
                )
            except Exception:
                logging.exception("Harness 事件持久化失败 run_id=%s", run_id)

        try:
            await app.state.session_store.start_run(
                run_id=run_id,
                session_id=req.session_id,
                turn_number=turn_number,
                started_at=started_at,
            )
            await persist_event({
                "event_type": "turn/start",
                "node": "START",
                "turn_number": turn_number,
            })
        except Exception:
            logging.exception("Harness Run 建档失败 run_id=%s", run_id)
        yield _sse("graph", {
            "run_id": run_id,
            "turn_number": turn_number,
            "nodes": [
                "TurnContext", "ContextCompaction", "Agent", "ToolExecution", "END",
            ],
            "edges": [
                "START → TurnContext", "TurnContext → ContextCompaction", "ContextCompaction → Agent",
                "Agent → ToolExecution", "ToolExecution → ContextCompaction", "Agent → END",
            ],
        })
        try:
            graph_input = {
                "messages": [_user_message(req, attachment_refs)],
                "current_attachments": [item.model_dump() for item in attachment_refs],
                "force_compaction": req.force_compaction,
            }
            async for mode, chunk in runtime.graph.astream(
                graph_input,
                config=config,
                stream_mode=["updates", "custom"],
            ):
                if mode == "custom":
                    if chunk.get("kind") == "model_token":
                        yield _sse("token", chunk)
                    for semantic_event in tracer.record_custom(chunk):
                        await persist_event(semantic_event)
                        yield _sse("trace", semantic_event)
                    continue
                for node, update in chunk.items():
                    event_update = dict(update or {})
                    node_event = tracer.record_node(node, event_update)
                    await persist_event(node_event)
                    yield _sse("node", node_event)

            snapshot = await runtime.graph.aget_state(config)
            result = dict(snapshot.values)
            response = _chat_response(result)
            await app.state.session_store.record_assistant_message(req.session_id, response.answer)
            elapsed_ms = tracer.finish(response.token_usage)
            persisted_metrics = response.context_metrics.model_dump()
            persisted_metrics["turn_token_usage"] = response.token_usage.model_dump()
            await persist_event({
                "event_type": "turn/end",
                "node": "END",
                "turn_number": turn_number,
                "elapsed_ms": elapsed_ms,
            })
            await app.state.session_store.finish_run(
                run_id=run_id,
                status="completed",
                elapsed_ms=elapsed_ms,
                compacted=response.compacted,
                context_metrics=persisted_metrics,
                tool_call_count=len(response.tool_trace),
            )
            yield _sse("final", {
                **response.model_dump(),
                "run_id": run_id,
                "turn_number": turn_number,
                "elapsed_ms": elapsed_ms,
                "final_edge": f"{tracer.previous_node or 'START'} → END",
            })
        except Exception as exc:
            logging.exception("Game_Rover 流式执行失败")
            elapsed_ms = int((datetime.now().astimezone() - started_at).total_seconds() * 1000)
            await persist_event({
                "event_type": "turn/error",
                "node": tracer.previous_node,
                "turn_number": turn_number,
                "elapsed_ms": elapsed_ms,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:1000],
            })
            try:
                await app.state.session_store.finish_run(
                    run_id=run_id,
                    status="failed",
                    elapsed_ms=elapsed_ms,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:1000],
                )
            except Exception:
                logging.exception("Harness 失败 Run 闭合失败 run_id=%s", run_id)
            yield _sse("error", {"detail": str(exc)})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/ai/sessions")
async def list_sessions():
    return {"sessions": await app.state.session_store.list_sessions()}


@app.get("/ai/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    messages = await app.state.session_store.get_messages(session_id)
    if messages:
        if any(
            attachment and not attachment.get("data_url")
            for message in messages
            for attachment in (message.get("attachments") or [])
        ):
            config = {"configurable": {"thread_id": session_id}}
            snapshot = await app.state.game_assistant.graph.aget_state(config)
            if snapshot.values:
                messages = _restore_legacy_attachment_urls(messages, snapshot.values.get("messages", []))
        return {"session_id": session_id, "messages": messages}

    config = {"configurable": {"thread_id": session_id}}
    snapshot = await app.state.game_assistant.graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="session not found")
    fallback = []
    for message in snapshot.values.get("messages", []):
        if message.type == "human":
            fallback.append({"role": "user", "content": message.content})
        elif message.type == "ai" and message.content:
            fallback.append({"role": "assistant", "content": message.content})
    return {"session_id": session_id, "messages": fallback}


@app.get("/ai/sessions/{session_id}/attachments/{attachment_id}")
async def attachment_content(session_id: str, attachment_id: str):
    attachment = await app.state.session_store.get_attachment(attachment_id, session_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="attachment not found")
    return Response(
        content=bytes(attachment["content"]),
        media_type=attachment["mime_type"],
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@app.get("/ai/sessions/{session_id}/runs")
async def session_runs(session_id: str, limit: int = 20):
    return {
        "session_id": session_id,
        "runs": await app.state.session_store.list_runs(session_id, max(1, min(limit, 50))),
    }


@app.patch("/ai/sessions/{session_id}")
async def rename_session(session_id: str, req: SessionRenameRequest):
    title = " ".join(req.title.split())
    if not title:
        raise HTTPException(status_code=422, detail="title cannot be blank")
    if not await app.state.session_store.rename_session(session_id, title):
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "title": title}


@app.delete("/ai/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    deleted = await app.state.session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    await app.state.game_assistant.graph.checkpointer.adelete_thread(session_id)


@app.get("/ai/sessions/{session_id}/state")
async def inspect_session(session_id: str):
    config = {"configurable": {"thread_id": session_id}}
    snapshot = await app.state.game_assistant.graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="session not found")
    state = dict(snapshot.values)
    state["messages"] = [
        {
            "id": message.id,
            "type": message.type,
            "name": getattr(message, "name", None),
            "content": message.content,
            "tool_calls": getattr(message, "tool_calls", []),
        }
        for message in state.get("messages", [])
    ]
    return state


@app.get("/ai/health")
async def health():
    return {
        "status": "ok",
        "architecture": "single-agent-budgeted-harness",
        "persistence": "postgresql",
        "tools": ["skill", "read_skill_reference", "web_search"],
        "skills": [item.name for item in app.state.game_assistant.skill_registry.catalog()],
    }
