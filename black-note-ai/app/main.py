"""
app/main.py

按照官方文档 Streaming 页面的 version="v2" 写法。

文档关键变化：
  1. stream() 必须传 version="v2" 才能用新格式
  2. 新格式每个 chunk 是 {"type": ..., "ns": ..., "data": ...}
     文档原文：
     "Pass version='v2' to stream() or astream() to get a unified output format.
      Every chunk is a StreamPart dict with a consistent shape."
  3. 过滤 messages 的写法变成：
     if chunk["type"] == "messages":
         msg, metadata = chunk["data"]
  4. 过滤节点用 metadata["langgraph_node"]
     文档原文：
     "To stream tokens only from specific nodes, use stream_mode='messages'
      and filter the outputs by the langgraph_node field in the metadata"
"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain.messages import HumanMessage, SystemMessage
from app.core.prompts import ROVER_SYSTEM_PROMPT     

from app.core.graph import build_graph
from app.auth import get_request_user_id
from app.core.schemas import ChatRequest
from app.storage.sync import get_vectorstore, sync_single_note, delete_note_from_vectorstore
from app.storage.embeddings import _get_model  # 直接调单例初始化函数
from fastapi import BackgroundTasks

load_dotenv()

'''
@asynccontextmanager是 Python 的异步上下文管理器装饰器，
让你用 async def + yield 的写法来定义"启动时做什么、关闭时做什么"。

yield 是分界线：

yield 之前 → 应用启动时执行
yield 之后 → 应用关闭时执行
'''
@asynccontextmanager
async def lifespan(app: FastAPI):
    """只在启动时构建一次 graph，缓存到 app.state"""
    print("🚀 启动 AI 服务...")
    _get_model()
    app.state.graph = build_graph(get_vectorstore())
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

    # 立刻返回给 Spring Boot，同步在后台执行
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
    graph = app.state.graph  # 复用全局单例

    # 文档写法：thread_id 放在 configurable 里
    # 同时把 user_id 也放进去，工具函数从这里取
    config = {
        "configurable": {
            "thread_id": f"{user_id}:{req.session_id}",
            "user_id":   user_id,
        }
    }
    def generate():
        """
        按文档 Streaming v2 写法，同时开 messages + updates 两个模式。

        messages → 推送 LLM token（前端流式显示）
        updates  → 推送节点状态变化（前端调试面板）

        调试事件格式：[DEBUG:type:value]
          [DEBUG:llm_call:1]          → LLM 第1次调用
          [DEBUG:tool:search_notes]   → 调用了 search_notes 工具
        """
        try:
            for chunk in graph.stream(
                input={
                    # 第一次对话：checkpointer 里没有历史，SystemMessage 会被写入持久化
                    # 后续对话：checkpointer 已有历史，LangGraph 会把这里的消息 append 进去
                    # 所以 SystemMessage 只在第一条消息时生效，不会重复累积
                    "messages": [
                        SystemMessage(content=ROVER_SYSTEM_PROMPT),
                        HumanMessage(content=req.question),
                    ],
                    "user_id":   user_id,
                    "llm_calls": 0,
                },
                config=config,
                stream_mode=["messages", "updates"],   # 文档写法：列表同时开多个模式
                version="v2",                          # 文档要求，启用统一格式
            ):
                # ── updates 模式：节点状态变化，用于调试面板 ──────────
                if chunk["type"] == "updates":
                    for node_name, update in chunk["data"].items():
                        if node_name == "llm_call":
                            calls = update.get("llm_calls", "?")
                            yield f"data: [DEBUG:llm_call:{calls}]\n\n"

                            # ← 同时从这里取工具名，比从 ToolMessage 取更可靠
                            msgs = update.get("messages", [])
                            for m in msgs:
                                for tc in getattr(m, "tool_calls", []):
                                    tool_name = tc.get("name", "tool")
                                    yield f"data: [DEBUG:tool:{tool_name}]\n\n"
                # ── messages 模式：LLM token，用于流式显示 ────────────
                elif chunk["type"] == "messages":
                    # 文档写法：从 chunk["data"] 解包 (msg, metadata)
                    msg, metadata = chunk["data"]

                    # 文档写法：用 metadata["langgraph_node"] 过滤节点
                    is_ai_text = (
                        metadata.get("langgraph_node") == "llm_call"
                        and msg.content
                        and not getattr(msg, "tool_call_chunks", None)
                    )

                    if is_ai_text:
                        # 换行符转义，防止 SSE 协议把 \n 当分隔符吃掉
                        content = msg.content.replace("\n", "\\n")
                        yield f"data: {content}\n\n"

        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            print(f"Graph 执行错误: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 健康检查 ──────────────────────────────────────────────────
@app.get("/ai/health")
async def health():
    count = get_vectorstore()._collection.count()
    return {"status": "ok", "notes_indexed": count}