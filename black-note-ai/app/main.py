from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from .agent import build_agent, init_agent_context
from .auth import get_request_user_id
from .rag import build_rag_chain
from .schemas import ChatRequest, AgentRequest, SyncRequest, DeleteRequest
from .store.vectorstore import (
    delete_note_from_vectorstore,
    get_vectorstore,
    sync_single_note,
)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动AI服务，加载向量库和Agent...")
    app.state.vectorstore = get_vectorstore()
    app.state.agent = build_agent()
    init_agent_context(app.state.vectorstore, "0")

    try:
        await redis_client.ping()
        print("✅ Redis连接就绪（用于直连token兜底）")
    except Exception as e:
        print(f"⚠️ Redis连接不可用（直连token兜底会失败）: {e}")

    print("✅ AI服务就绪")
    yield
    try:
        await redis_client.aclose()
    except Exception:
        pass
    print("🛑 AI服务关闭")


app = FastAPI(title="小黑书AI助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/ai/chat")
async def chat(req: ChatRequest, user_id: str = Depends(get_request_user_id)):
    vectorstore = app.state.vectorstore
    rag_chain = build_rag_chain(vectorstore, user_id)

    async def generate():
        try:
            async for chunk in rag_chain.astream(
                {"input": req.question},
                config={"configurable": {"session_id": req.session_id}},
            ):
                if chunk:
                    yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/ai/agent")
async def agent_task(req: AgentRequest):
    init_agent_context(app.state.vectorstore, req.user_id)
    agent = app.state.agent

    async def generate():
        try:
            async for chunk in agent.astream({"messages": [HumanMessage(content=req.task)]}):
                if "agent" in chunk:
                    msg = chunk["agent"]["messages"][-1]
                    if msg.content and not getattr(msg, "tool_calls", None):
                        yield f"data: {msg.content}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/ai/search")
async def search(q: str, user_id: str = Depends(get_request_user_id)):
    vectorstore = app.state.vectorstore
    results = vectorstore.similarity_search_with_score(q, k=10, filter={"user_id": user_id})

    notes = []
    for doc, score in results:
        if 1 - score >= 0.3:
            notes.append(
                {
                    "note_id": doc.metadata.get("note_id"),
                    "title": doc.metadata.get("title"),
                    "author": doc.metadata.get("author"),
                    "similarity": round(1 - score, 4),
                    "summary": (doc.page_content or "")[:100],
                }
            )
    return {"notes": notes, "total": len(notes)}


@app.post("/ai/sync_note")
async def sync_note(req: SyncRequest):
    success = sync_single_note(req.note_id)
    if not success:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return {"message": f"笔记 {req.note_id} 同步成功"}


@app.post("/ai/delete_note")
async def delete_note(req: DeleteRequest):
    success = delete_note_from_vectorstore(req.note_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    return {"message": f"笔记 {req.note_id} 已从向量库删除"}


@app.get("/ai/health")
async def health():
    count = app.state.vectorstore._collection.count()
    return {"status": "ok", "notes_count": count}

