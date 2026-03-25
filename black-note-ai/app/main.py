"""
app/main.py - 异步版

相对原版的变化：
  1. generate() 从同步生成器改为异步生成器（async def + async for）
  2. graph.stream 换成 graph.astream，整条链路全部异步，不占用线程池
  3. chat() 端点改为 async def，配合异步生成器
  4. get_state 改为 aget_state，避免在异步上下文里调用同步阻塞

最佳实践说明：
  - FastAPI 本身是异步框架，同步阻塞调用（如 graph.stream）会占用线程池
  - 高并发时线程池耗尽会导致新请求排队等待
  - 改成 astream 后每个请求只占用一个协程，并发能力大幅提升
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.auth import get_request_user_id
from app.core.graph import build_graph
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.core.schemas import ChatRequest
from app.storage.embeddings import _get_model
from app.storage.sync import (
    delete_note_from_vectorstore,
    get_vectorstore,
    sync_single_note,
)

load_dotenv()

# # 关掉 httpx 的 INFO 日志，避免每次 LLM 调用都打一行
# logging.getLogger("httpx").setLevel(logging.WARNING)


# ── 启动 / 关闭生命周期 ───────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动 AI 服务...")
    _get_model()   # 预热 bge-m3，避免第一次请求时才加载
    # checkpointer 的生命周期和应用一致，应用关闭时才释放连接
    async with AsyncSqliteSaver.from_conn_string("./checkpoints.db") as checkpointer:
        app.state.graph = build_graph(get_vectorstore(), checkpointer)
        print("✅ AI 服务就绪")
        yield
    print("🛑 AI 服务关闭")


app = FastAPI(title="小黑书AI助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 内部同步接口 ──────────────────────────────────────────────
@app.post("/internal/sync-note")
async def internal_sync_note(payload: dict, background_tasks: BackgroundTasks):
    note_id = payload.get("note_id")
    action  = payload.get("action", "sync")

    if not note_id:
        return {"success": False, "message": "缺少 note_id"}

    if action == "delete":
        background_tasks.add_task(delete_note_from_vectorstore, note_id)
    else:
        background_tasks.add_task(sync_single_note, note_id)

    return {"success": True, "note_id": note_id, "action": action, "status": "queued"}


# ── 主问答接口 ────────────────────────────────────────────────
@app.post("/ai/chat")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_request_user_id),
):
    graph = app.state.graph

    config = {
        "configurable": {
            "thread_id": f"{user_id}:{req.session_id}",
            "user_id": user_id,
        }
    }

    # ── 异步生成器：核心改动 ──────────────────────────────────
    # 原来：def generate() + for chunk in graph.stream(...)
    # 现在：async def generate() + async for chunk in graph.astream(...)
    #
    # 好处：
    #   - 不阻塞 event loop，FastAPI 可以同时处理其他请求
    #   - 不占用线程池，高并发时不会出现线程耗尽
    async def generate():
        try:
            # 检查当前 thread 是否已有历史消息
            # aget_state 是 get_state 的异步版，避免在异步上下文里调同步方法
            saved = await graph.aget_state(config)
            existing_messages = (
                saved.values.get("messages", []) if saved.values else []
            )

            # 只有第一次对话（没有历史）才注入 SystemMessage
            # checkpointer 会持久化，后续轮次自动携带，不需要重复注入
            if not existing_messages:
                input_messages = [
                    SystemMessage(content=ROVER_SYSTEM_PROMPT),
                    HumanMessage(content=req.question),
                ]
            else:
                input_messages = [HumanMessage(content=req.question)]

            # graph.astream 是 graph.stream 的异步版本
            # async for 不阻塞，每个 chunk 到来时才恢复执行
            async for chunk in graph.astream(
                input={
                    "messages": input_messages,
                    "user_id": user_id,
                    "llm_calls": 0,   # 每次新请求强制重置为 0
                },
                config=config,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                # ── updates：调试面板事件 ──────────────────────
                if chunk["type"] == "updates":
                    for node_name, update in chunk["data"].items():
                        if node_name == "llm_call":
                            calls = update.get("llm_calls", "?")
                            yield f"data: [DEBUG:llm_call:{calls}]\n\n"

                            msgs = update.get("messages", [])
                            for m in msgs:
                                for tc in getattr(m, "tool_calls", []):
                                    tool_name = tc.get("name", "tool")
                                    yield f"data: [DEBUG:tool:{tool_name}]\n\n"

                # ── messages：LLM token 流式输出 ──────────────
                elif chunk["type"] == "messages":
                    msg, metadata = chunk["data"]

                    is_ai_text = (
                        metadata.get("langgraph_node") == "llm_call"
                        and msg.content
                        and not getattr(msg, "tool_call_chunks", None)
                    )

                    if is_ai_text:
                        # 换行符转义，防止 SSE 协议把 \n 当分隔符处理
                        content = msg.content.replace("\n", "\\n")
                        yield f"data: {content}\n\n"

        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            print(f"Graph 执行错误: {e}")

    # StreamingResponse 支持异步生成器，直接传入即可
    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 健康检查 ──────────────────────────────────────────────────
@app.get("/ai/health")
async def health():
    count = get_vectorstore()._collection.count()
    return {"status": "ok", "notes_indexed": count}