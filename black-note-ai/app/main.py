"""
app/main.py

FastAPI 应用入口。整合所有业务路由 + AI 聊天路由。

启动命令：
  uvicorn app.main:app --port 8001 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.mongodb.aio import AsyncMongoDBSaver

from app.auth import get_request_user_id
from app.common import BusinessException, Result
from app.config import settings
from app.core.graph import build_graph
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.core.schemas import ChatRequest
from app.database import init_db
from app.storage.embeddings import _get_model
from app.storage.sync import get_vectorstore, get_sync_qdrant_client

from app.routers import user, note, follow, feed, file, chat_session


# ── 应用生命周期 ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("启动服务...")
    # 初始化 Beanie Document 模型（确保集合和索引存在）
    await init_db()
    # 预热 embedding 模型
    _get_model()
    # 确保 Qdrant 集合存在
    get_sync_qdrant_client()

    async with AsyncMongoDBSaver.from_conn_string(
        settings.MONGODB_URL, db_name=settings.MONGODB_DB
    ) as checkpointer:
        app.state.graph = build_graph(get_vectorstore(), checkpointer)
        logging.info("服务就绪")
        yield
    logging.info("服务关闭")


app = FastAPI(title="小黑书 API", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──────────────────────────────────────────────────
@app.exception_handler(BusinessException)
async def business_exception_handler(request: Request, exc: BusinessException):
    return JSONResponse(
        status_code=exc.status_code,
        content=Result.fail(exc.status_code, exc.detail).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logging.exception("未处理异常")
    return JSONResponse(
        status_code=500,
        content=Result.fail(500, "服务器内部错误").model_dump(),
    )


# ── 业务路由 ──────────────────────────────────────────────────────
app.include_router(user.router)
app.include_router(note.router)
app.include_router(follow.router)
app.include_router(feed.router)
app.include_router(file.router)
app.include_router(chat_session.router)


# ── AI 聊天接口 ───────────────────────────────────────────────────
@app.post("/ai/chat")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_request_user_id),
):
    graph = app.state.graph
    config = {
        "configurable": {
            "thread_id": f"{user_id}:{req.session_id}",
            "user_id":   user_id,
        }
    }

    async def generate():
        try:
            saved = await graph.aget_state(config)
            existing_messages = saved.values.get("messages", []) if saved.values else []

            if not existing_messages:
                input_messages = [
                    SystemMessage(content=ROVER_SYSTEM_PROMPT),
                    HumanMessage(content=req.question),
                ]
            else:
                input_messages = [HumanMessage(content=req.question)]

            async for chunk in graph.astream(
                input={"messages": input_messages, "user_id": user_id, "llm_calls": 0},
                config=config,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                if chunk["type"] == "updates":
                    for node_name, update in chunk["data"].items():
                        if node_name == "llm_call":
                            calls = update.get("llm_calls", "?")
                            yield f"data: [DEBUG:llm_call:{calls}]\n\n"
                            for m in update.get("messages", []):
                                for tc in getattr(m, "tool_calls", []):
                                    yield f"data: [DEBUG:tool:{tc.get('name', 'tool')}]\n\n"

                elif chunk["type"] == "messages":
                    msg, metadata = chunk["data"]
                    is_ai_text = (
                        metadata.get("langgraph_node") == "llm_call"
                        and msg.content
                        and not getattr(msg, "tool_call_chunks", None)
                    )
                    if is_ai_text:
                        content = msg.content.replace("\n", "\\n")
                        yield f"data: {content}\n\n"

        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            logging.exception("Graph 执行错误")

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 健康检查 ──────────────────────────────────────────────────────
@app.get("/ai/health")
async def health():
    try:
        client = get_sync_qdrant_client()
        info   = client.get_collection(settings.QDRANT_COLLECTION)
        count  = info.points_count
    except Exception:
        count = -1
    return {"status": "ok", "notes_indexed": count}
