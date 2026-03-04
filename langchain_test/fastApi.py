import os
from fastapi import FastAPI,Header,HTTPException



async def lifespan(app:FastAPI):
    app.state.db = {"1": "Redis缓存穿透笔记", "2": "LeetCode刷题笔记"}
    yield



app = FastAPI(title="我的第一个FastAPI", lifespan=lifespan)


# 请求定义
class NoteRequest(BaseModel):
    title:   str
    content: str
    tags:    str = "默认标签"  # 有默认值，可以不传
class SearchRequest(BaseModel):
    keyword: str
    limit:   int = 5  # 默认返回5条

# ── 第三：路由 ────────────────────────────────────

# GET请求，无请求体，参数从URL或Header取
@app.get("/note/{note_id}")
async def get_note(
    note_id: str,                                    # 从URL路径取
    x_user_id: str = Header(..., alias="X-User-Id")  # 从Header取，必填
):
    db = app.state.db
    if note_id not in db:
        raise HTTPException(status_code=404, detail=f"笔记{note_id}不存在")

    return {
        "note_id":  note_id,
        "title":    db[note_id],
        "user_id":  x_user_id,
    }


# POST请求，有请求体
@app.post("/note")
async def create_note(
    req: NoteRequest,
    x_user_id: str = Header(..., alias="X-User-Id")
):
    # 模拟保存
    new_id = str(len(app.state.db) + 1)
    app.state.db[new_id] = req.title

    return {
        "message":  "创建成功",
        "note_id":  new_id,
        "title":    req.title,
        "content":  req.content,
        "tags":     req.tags,
        "user_id":  x_user_id,
    }


# 流式返回
@app.post("/note/stream")
async def stream_note(req: SearchRequest):
    async def generate():
        words = f"正在搜索关键词：{req.keyword}，限制{req.limit}条结果...".split("，")
        for word in words:
            yield f"data: {word}\n\n"
            await asyncio.sleep(0.5)  # 模拟耗时操作
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# 健康检查
@app.get("/health")
async def health():
    return {"status": "ok", "notes_count": len(app.state.db)}