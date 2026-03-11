import asyncio
import os
from contextlib import asynccontextmanager
import json
import aio_pika
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from .agent import build_agent
from .auth import get_request_user_id
from .rag import build_rag_chain
from .schemas import AgentRequest, ChatRequest
from .store.vectorstore import (
    delete_note_from_vectorstore,
    get_vectorstore,
    sync_single_note,
)

load_dotenv()


async def start_mq_consumer(vectorstore):
    """内置 RabbitMQ 消费者，随 FastAPI 一起启动"""
    url = (
        f"amqp://{os.getenv('RABBITMQ_USER', 'guest')}:"
        f"{os.getenv('RABBITMQ_PASSWORD', 'guest')}@"
        f"{os.getenv('RABBITMQ_HOST', '127.0.0.1')}/"
    )
    connection = await aio_pika.connect_robust(url)
    channel = await connection.channel()

    sync_queue = await channel.declare_queue("note.sync.queue", durable=True)

    async def on_message(msg: aio_pika.IncomingMessage):
        async with msg.process():
            note_id = int(json.loads(msg.body.decode()))
            if note_id > 0:
                # 正数：同步笔记
                success = sync_single_note(note_id)
                print(f"{'✅' if success else '❌'} 笔记{note_id}同步{'成功' if success else '失败'}")
            else:
                # 负数：删除笔记
                real_id = abs(note_id)
                success = delete_note_from_vectorstore(real_id)
                print(f"{'✅' if success else '❌'} 笔记{real_id}删除{'成功' if success else '失败'}")

    await sync_queue.consume(on_message)
    print("🐰 MQ消费者已启动，监听 note.sync.queue")
    await asyncio.Future()  


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 启动AI服务，加载向量库...")
    app.state.vectorstore = get_vectorstore()

    # 内置MQ消费者，随FastAPI一起启动，不需要单独开终端
    asyncio.create_task(start_mq_consumer(app.state.vectorstore))

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


# ── RAG 问答：流式输出 ──
@app.post("/ai/chat")
async def chat(req: ChatRequest, user_id: str = Depends(get_request_user_id)):
    rag_chain = build_rag_chain(app.state.vectorstore, user_id)
    config = {"configurable": {"session_id": req.session_id}}

    def generate():
        try:
            for chunk in rag_chain.stream({"input": req.question}, config=config):
                if chunk:
                    yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Agent：流式输出 + 短期记忆 ──
@app.post("/ai/agent")
async def agent_task(req: AgentRequest, user_id: str = Depends(get_request_user_id)):
    agent = build_agent(app.state.vectorstore, user_id)
    config = {"configurable": {"thread_id": user_id}}

    # reset=True 时清除该用户的对话历史
    if req.reset:
        agent.checkpointer.storage.pop(user_id, None)

    def generate():
        try:
            for event in agent.stream(
                input={"messages": [HumanMessage(content=req.task)]},
                config=config,
                stream_mode=["messages", "updates"],
            ):
                mode, chunk = event
                if mode == "messages":
                    msg_chunk, _ = chunk
                    if msg_chunk.content and isinstance(msg_chunk.content, str):
                        yield f"data: {msg_chunk.content}\n\n"
                elif mode == "updates":
                    for _, update in chunk.items():
                        last_msg = update.get("messages", [None])[-1]
                        if last_msg and getattr(last_msg, "tool_calls", None):
                            yield f"data: [正在查询：{last_msg.tool_calls[0]['name']}]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 语义搜索 ──
@app.get("/ai/search")
async def search(q: str, user_id: str = Depends(get_request_user_id)):
    results = app.state.vectorstore.similarity_search_with_score(
        q, k=10, filter={"user_id": user_id}
    )
    notes = []
    for doc, score in results:
        similarity = round(1 - score, 4)
        if similarity >= 0.1:
            notes.append({
                "note_id":   doc.metadata.get("note_id"),
                "title":     doc.metadata.get("title"),
                "author":    doc.metadata.get("author"),
                "similarity": similarity,
                "summary":   (doc.page_content or "")[:100],
            })
    return {"notes": notes, "total": len(notes)}


# ── 健康检查 ──
@app.get("/ai/health")
async def health():
    count = app.state.vectorstore._collection.count()
    return {"status": "ok", "notes_indexed": count}