import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain.tools import tool       
from langchain.agents import create_agent 
from langchain.messages import SystemMessage, HumanMessage

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

# 向量库
from embeddings import BGEEmbeddings
from langchain_chroma import Chroma

vectorstore = Chroma(
    persist_directory="../black-note-ai/chroma_db",
    embedding_function=BGEEmbeddings(),
    collection_name="black_note_all"
)

# ✅ 官方文档写法：用 @tool 装饰器，函数有类型注解和 docstring
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


# ✅ 官方文档写法：create_agent(model, tools=[], system_prompt="")
agent = create_agent(
    llm,
    tools=[search_notes, get_note_detail, get_note_list],
    system_prompt=SystemMessage(
        content=[]
    )
)

# ✅ 官方文档调用方式
if __name__ == "__main__":
    response = agent.invoke({
        "messages": [
            SystemMessage("你是一位我的研究助手，导师，好朋友"),
            HumanMessage("请给给我一些学习上的建议"),
        ]
    })
    print(response["messages"][-1].content )