"""
FastAPI 主服务入口（app/main.py）
去掉 MQ 版本 - 使用 HTTP 回调进行增量同步（2026 年中小项目推荐方案）

核心功能：
- /ai/chat：Agent + RAG 主问答接口（支持工具调用 + 记忆）
- /ai/search：纯向量搜索（前端预览用）
- /ai/health：健康检查
- /internal/sync-note：供 Spring Boot 调用（笔记保存/删除后同步向量库）
"""

import os
from dotenv import load_dotenv

from fastapi import Depends, FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

# 核心模块
from .agent import build_agent
from .auth import get_request_user_id
from .schemas import AgentRequest, ChatRequest

# 同步模块（HTTP 回调使用）
from app.sync import *

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理（简化版）"""
    print("🚀 启动 AI 服务，加载向量库...")
    app.state.vectorstore = get_vectorstore()
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


# ── 内部同步接口（供 Spring Boot 调用） ──
@app.post("/internal/sync-note")
async def internal_sync_note(payload: dict):
    """
    内部同步接口（仅供笔记后端 Spring Boot 调用）
    action = "sync" 或 "delete"
    """
    note_id = payload.get("note_id")
    action = payload.get("action", "sync")

    if not note_id:
        return {"success": False, "message": "缺少 note_id"}

    if action == "delete":
        success = delete_note_from_vectorstore(note_id)
    else:
        success = sync_single_note(note_id)

    return {"success": success, "note_id": note_id, "action": action}


# ── 统一 Agent 问答接口（主接口） ──
@app.post("/ai/chat")
async def chat(req: ChatRequest, user_id: str = Depends(get_request_user_id)):
    """
    主问答接口：支持 Agent + RAG Tool + 短期记忆
    推荐前端统一调用此接口
    """
    agent = build_agent(app.state.vectorstore, user_id)
    config = {"configurable": {"thread_id": user_id}}

    # 支持重置记忆
    if hasattr(req, "reset") and req.reset:
        agent.checkpointer.storage.pop(user_id, None)

    def generate():
        try:
            for event in agent.stream(
                input={"messages": [HumanMessage(content=req.question)]},
                config=config,
                stream_mode=["messages", "updates"],
            ):
                mode, chunk = event
                if mode == "messages":
                    msg_chunk, _ = chunk
                    if msg_chunk.content and isinstance(msg_chunk.content, str):
                        if "tool_calls" not in msg_chunk.additional_kwargs:
                            yield f"data: {msg_chunk.content}\n\n"
                        else:
                            yield f"data: [思考中...]\n\n"
                elif mode == "updates":
                    for _, update in chunk.items():
                        last_msg = update.get("messages", [None])[-1]
                        if last_msg and getattr(last_msg, "tool_calls", None):
                            tool_name = last_msg.tool_calls[0].get("name", "未知工具")
                            yield f"data: [正在调用工具：{tool_name}]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            print(f"Agent 执行错误: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 纯语义搜索接口 ──
@app.get("/ai/search")
async def search(q: str, user_id: str = Depends(get_request_user_id)):
    """纯向量搜索，用于前端快速预览"""
    results = app.state.vectorstore.similarity_search_with_score(
        q, k=10, filter={"user_id": user_id}
    )
    notes = []
    for doc, score in results:
        similarity = round(1 - score, 4)
        if similarity >= 0.1:
            notes.append({
                "note_id": doc.metadata.get("note_id"),
                "title": doc.metadata.get("title", "无标题"),
                "author": doc.metadata.get("author", "未知"),
                "similarity": similarity,
                "summary": (doc.page_content or "")[:120] + "..." if len(doc.page_content) > 120 else doc.page_content,
            })
    return {"notes": notes, "total": len(notes)}


# ── 健康检查 ──
@app.get("/ai/health")
async def health():
    """服务健康检查"""
    count = app.state.vectorstore._collection.count()
    return {
        "status": "ok",
        "notes_indexed": count,
        "vectorstore_type": "Chroma",
        "timestamp": os.getenv("BUILD_TIME", "未知")
    }