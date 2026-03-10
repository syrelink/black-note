import os
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import SystemMessage
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import create_engine, text

load_dotenv()

_CURRENT_USER_ID: Optional[str] = None
_VECTORSTORE = None

engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)


def init_agent_context(vectorstore, user_id: str):
    global _CURRENT_USER_ID, _VECTORSTORE
    _CURRENT_USER_ID = str(user_id)
    _VECTORSTORE = vectorstore


@tool
def search_notes(query: str) -> str:
    """根据语义搜索笔记，返回相关笔记的 ID 和标题列表（仅当前用户）。"""
    if _VECTORSTORE is None or _CURRENT_USER_ID is None:
        return "Agent未初始化：缺少vectorstore或user_id"

    docs = _VECTORSTORE.similarity_search_with_score(
        query, 3, filter={"user_id": _CURRENT_USER_ID}
    )
    if not docs:
        return "未找到相关笔记"
    return "\n".join(
        f"ID: {doc.metadata.get('note_id', '未知')} 标题: {doc.metadata.get('title', '无标题')}"
        for doc, _ in docs
    )


@tool
def get_note_detail(note_id: str) -> str:
    """根据笔记 ID 获取笔记详情（仅当前用户）。"""
    if _CURRENT_USER_ID is None:
        return "Agent未初始化：缺少user_id"
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT title, content, created_at FROM note "
                    "WHERE id = :id AND user_id = :user_id AND is_deleted = 0"
                ),
                {"id": note_id, "user_id": _CURRENT_USER_ID},
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
    if _CURRENT_USER_ID is None:
        return "Agent未初始化：缺少user_id"
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT id, title, created_at FROM note "
                    "WHERE user_id = :user_id AND is_deleted = 0 "
                    "ORDER BY created_at DESC"
                ),
                {"user_id": _CURRENT_USER_ID},
            )
            notes = result.fetchall()
        if not notes:
            return "暂无笔记"
        return "\n".join(f"ID: {n[0]} 标题: {n[1]} 时间: {n[2]}" for n in notes)
    except Exception as e:
        return f"查询失败：{e}"


def build_agent():
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
        streaming=True,
    )

    return create_agent(
        llm,
        tools=[search_notes, get_note_detail, get_note_list],
        system_prompt=SystemMessage(
            content="你是用户的私人笔记助手。你可以使用工具检索/读取用户笔记来完成任务。"
        ),
    )

