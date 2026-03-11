import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, text

load_dotenv()

engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)

# 全局记忆存储，服务重启前一直保留对话历史
_checkpointer = InMemorySaver()


def make_tools(vectorstore, user_id: str):
    """工具工厂：通过闭包注入 user_id，每次请求生成独立工具，多用户并发安全。"""

    @tool
    def search_notes(query: str) -> str:
        """根据语义搜索笔记，返回相关笔记的 ID 和标题列表（仅当前用户）。"""
        docs = vectorstore.similarity_search_with_score(
            query, k=3, filter={"user_id": user_id}
        )
        if not docs:
            return "未找到相关笔记"
        return "\n".join(
            f"ID: {doc.metadata.get('note_id', '未知')} 标题: {doc.metadata.get('title', '无标题')}"
            for doc, _ in docs
        )

    @tool
    def get_note_detail(note_id: str) -> str:
        """根据笔记 ID 获取笔记完整内容。"""
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT title, content, created_at FROM note "
                        "WHERE id = :id AND user_id = :user_id AND is_deleted = 0"
                    ),
                    {"id": note_id, "user_id": user_id},
                )
                note = result.fetchone()
            if not note:
                return f"笔记 {note_id} 不存在或无权访问"
            return f"标题：{note[0]}\n时间：{note[2]}\n内容：{note[1]}"
        except Exception as e:
            return f"查询失败：{e}"

    @tool
    def get_note_list(_: str = "") -> str:
        """获取当前用户所有笔记的标题列表。"""
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT id, title, created_at FROM note "
                        "WHERE user_id = :user_id AND is_deleted = 0 "
                        "ORDER BY created_at DESC"
                    ),
                    {"user_id": user_id},
                )
                notes = result.fetchall()
            if not notes:
                return "暂无笔记"
            return "\n".join(f"ID: {n[0]} 标题: {n[1]} 时间: {n[2]}" for n in notes)
        except Exception as e:
            return f"查询失败：{e}"

    return [search_notes, get_note_detail, get_note_list]


def build_agent(vectorstore, user_id: str):
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
        streaming=True,
    )

    tools = make_tools(vectorstore, user_id)

    # checkpointer 开启短期记忆，thread_id 区分不同用户的对话
    return create_agent(
        llm,
        tools=tools,
        system_prompt=SystemMessage(
            content="你是用户的私人笔记助手。你可以使用工具检索/读取用户笔记来完成任务。"
        ),
        checkpointer=_checkpointer,
    )