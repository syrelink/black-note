import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from embeddings import BGEEmbeddings
from vectorstore import get_vectorstore, sync_single_note, delete_note_from_vectorstore
from rag import build_rag_chain, get_session_history
from agent import build_agent, init_agent_context

load_dotenv()

# ── 启动时初始化，只加载一次 ──────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动AI服务，加载模型和向量库...")
    app.state.vectorstore = get_vectorstore()
    app.state.agent       = build_agent()
    init_agent_context(app.state.vectorstore, "0")  # 默认占位
    print("✅ AI服务就绪")
    yield
    print("🛑 AI服务关闭")

app = FastAPI(title="小黑书AI助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求体定义 ────────────────────────────────────
class ChatRequest(BaseModel):
    question:   str
    session_id: str = "default"

class AgentRequest(BaseModel):
    task:    str
    user_id: str

class SyncRequest(BaseModel):
    note_id: int

class DeleteRequest(BaseModel):
    note_id: int


# ── 工具函数：从JWT解析user_id ────────────────────
def parse_user_id(authorization: str) -> str:
    """
    生产环境应解析JWT Token拿user_id
    现在简化处理：直接从Header取X-User-Id
    """
    return authorization  # 暂时直接用Header值


# ── 接口1：RAG问答（SSE流式）─────────────────────
@app.post("/ai/chat")
async def chat(
    req: ChatRequest,
    x_user_id: str = Header(..., alias="X-User-Id")
):
    """
    RAG多轮问答，流式输出
    Header传X-User-Id，只查询该用户的笔记
    """
    vectorstore = app.state.vectorstore
    rag_chain   = build_rag_chain(vectorstore, x_user_id)

    async def generate():
        try:
            async for chunk in rag_chain.astream(
                {"input": req.question},
                config={"configurable": {"session_id": req.session_id}}
            ):
                if chunk:
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 接口2：Agent写作助手 ──────────────────────────
@app.post("/ai/agent")
async def agent_task(req: AgentRequest):
    """
    ReAct Agent处理复杂任务
    例：把技术笔记整理成文章、分析近期情绪状态
    """
    init_agent_context(app.state.vectorstore, req.user_id)
    agent = app.state.agent

    async def generate():
        try:
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=req.task)]}
            ):
                # 只输出最终回答，过滤工具调用过程
                if "messages" in chunk:
                    msg = chunk["messages"][-1]
                    if msg.type == "ai" and not getattr(msg, "tool_calls", None):
                        if msg.content:
                            yield f"data: {msg.content}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 接口3：语义搜索 ───────────────────────────────
@app.get("/ai/search")
async def search(
    q: str,
    x_user_id: str = Header(..., alias="X-User-Id")
):
    """
    语义搜索接口，替代MySQL的LIKE查询
    Spring Boot搜索接口调用此处
    """
    vectorstore = app.state.vectorstore
    results = vectorstore.similarity_search_with_score(
        q, k=10,
        filter={"user_id": x_user_id}
    )

    notes = []
    for doc, score in results:
        if 1 - score >= 0.3:
            notes.append({
                "note_id":    doc.metadata["note_id"],
                "title":      doc.metadata["title"],
                "author":     doc.metadata["author"],
                "similarity": round(1 - score, 4),
                "summary":    doc.page_content[:100],
            })

    return {"notes": notes, "total": len(notes)}


# ── 接口4：新笔记同步入库 ─────────────────────────
@app.post("/ai/sync_note")
async def sync_note(req: SyncRequest):
    """
    Spring Boot发布笔记后调用此接口
    增量向量化，不影响其他数据
    """
    success = sync_single_note(req.note_id)
    if not success:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return {"message": f"笔记 {req.note_id} 同步成功"}


# ── 接口5：删除笔记同步 ───────────────────────────
@app.post("/ai/delete_note")
async def delete_note(req: DeleteRequest):
    """
    Spring Boot删除笔记后调用，保持向量库和数据库一致
    """
    success = delete_note_from_vectorstore(req.note_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": f"笔记 {req.note_id} 已从向量库删除"}


# ── 健康检查 ──────────────────────────────────────
@app.get("/ai/health")
async def health():
    count = app.state.vectorstore._collection.count()
    return {"status": "ok", "notes_count": count}