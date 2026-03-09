import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain.tools import tool       
from langchain.agents import create_agent 
from langchain.messages import SystemMessage, HumanMessage
# 向量库
from embeddings import BGEEmbeddings
from langchain_chroma import Chroma
from pydantic import BaseModel
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()
CURRENT_USER_ID = 6

# LLM
llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model=os.getenv("DEEPSEEK_MODEL"),
    temperature=0.3,
)

# 数据库连接池
engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1/black_note",
    pool_size=5,
    max_overflow=10,
)


vectorstore = Chroma(
    persist_directory="../black-note-ai/chroma_db",
    embedding_function=BGEEmbeddings(),
    collection_name="black_note_all"
)

@tool
def search_notes(query: str) -> str:
    """根据语义搜索笔记，返回相关笔记的 ID 和标题列表。"""
    docs = vectorstore.similarity_search_with_score(
        query, 3, {"user_id": str(CURRENT_USER_ID)}
    )
    if not docs:
        return "未找到相关笔记"
    return "\n".join(
        f"ID: {doc.metadata.get('note_id', '未知')} 标题: {doc.metadata.get('title', '无标题')}"
        for doc, _ in docs
    )

@tool
def get_note_detail(note_id: str) -> str:
    """根据笔记 ID 获取笔记详情（标题、创建时间、内容）。请先用 search_notes 获取 ID。"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT title, content, created_at FROM note "
                    "WHERE id = :id AND user_id = :user_id AND is_deleted = 0"
                ),
                {"id": note_id, "user_id": CURRENT_USER_ID}
            )
            note = result.fetchone()
        if not note:
            return f"笔记 {note_id} 不存在或无权访问"
        return f"标题：{note[0]}\n时间：{note[2]}\n内容：{note[1]}"
    except Exception as e:
        return f"查询失败：{e}"

@tool
def get_note_list(placeholder: str = "") -> str:
    """获取当前用户所有笔记的标题列表。"""
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT id, title, created_at FROM note "
                    "WHERE user_id = :user_id AND is_deleted = 0 "
                    "ORDER BY created_at DESC"
                ),
                {"user_id": CURRENT_USER_ID}
            )
            notes = result.fetchall()
        if not notes:
            return "暂无笔记"
        return "\n".join(f"ID: {n[0]} 标题: {n[1]} 时间: {n[2]}" for n in notes)
    except Exception as e:
        return f"查询失败：{e}"

class ContactInfo(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None

# ✅ 官方文档写法：create_agent(model, tools=[], system_prompt="")
agent = create_agent(
    llm,
    tools=[search_notes, get_note_detail, get_note_list],
    checkpointer=InMemorySaver()
)
config = {
    "configurable":{"thread_id":1}
}


for chunk in agent.stream(
    {"messages":[HumanMessage("你觉得我写的最好的是哪一篇笔记")]},
    stream_mode="updates",
    config=config
):
    for step, data in chunk.items():
        print(f"step: {step}")
        print(f"content: {data['messages'][-1].content_blocks}")
        print()
    