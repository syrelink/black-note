import os
import pymysql
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

load_dotenv()

DB_CONFIG = {
    "host": "127.0.0.1", "port": 3306,
    "user": "root", "password": "123456",
    "database": "black_note", "charset": "utf8mb4",
}

# 全局变量，main.py初始化时注入
_vectorstore = None
_user_id     = None


def init_agent_context(vectorstore, user_id: str):
    global _vectorstore, _user_id
    _vectorstore = vectorstore
    _user_id     = user_id


@tool
def search_notes(query: str) -> str:
    """
    根据语义搜索用户的笔记，返回相关笔记列表。
    需要查找某个主题的笔记时使用。
    """
    docs = _vectorstore.similarity_search_with_score(
        query, k=5,
        filter={"user_id": _user_id}
    )
    if not docs:
        return "未找到相关笔记"

    results = []
    for doc, score in docs:
        if 1 - score >= 0.3:
            results.append(
                f"- ID:{doc.metadata['note_id']} "
                f"标题:{doc.metadata['title']} "
                f"摘要:{doc.page_content[:60]}..."
            )
    return "\n".join(results) if results else "未找到相关笔记"


@tool
def get_note_detail(note_id: str) -> str:
    """
    根据笔记ID获取笔记完整内容。
    需要读取某篇笔记详细内容时使用。
    """
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                "SELECT title, content, created_at FROM note "
                "WHERE id=%s AND user_id=%s AND is_deleted=0",
                (note_id, _user_id)
            )
            note = cursor.fetchone()
        conn.close()

        if not note:
            return f"笔记 {note_id} 不存在"
        return (f"标题：{note['title']}\n"
                f"时间：{note['created_at']}\n"
                f"内容：{note['content']}")
    except Exception as e:
        return f"获取失败：{e}"


def build_agent():
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
    )
    return create_react_agent(
        model=llm,
        tools=[search_notes, get_note_detail],
        prompt=(
            "你是用户的私人笔记助手，可以搜索和读取用户笔记。\n"
            "处理复杂任务时：先搜索相关笔记，再读取详情，最后整合回答。\n"
            "不要编造笔记中没有的内容。"
        )
    )