import os
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain.agents import create_agent
from langchain.messages import SystemMessage

load_dotenv()

# ── 由 FastAPI 注入的上下文（在 main.py 里通过 init_agent_context 设置） ──
_VECTORSTORE = None
_CURRENT_USER_ID: Optional[int] = None


def init_agent_context(vectorstore, user_id: str) -> None:
    """
    由 FastAPI 在每次 /ai/agent 请求前调用：
    - 注入全局 vectorstore
    - 设置当前会话对应的 user_id
    """
    global _VECTORSTORE, _CURRENT_USER_ID
    _VECTORSTORE = vectorstore
    _CURRENT_USER_ID = int(user_id)
    print(f"[Agent] 上下文已初始化：user_id={_CURRENT_USER_ID}")


# ── 数据库连接池（全局复用） ───────────────────────────────
engine = create_engine(
    "mysql+pymysql://root:123456@127.0.0.1/black_note",
    pool_size=5,
    max_overflow=10,
)


def _ensure_context():
    if _VECTORSTORE is None or _CURRENT_USER_ID is None:
        raise RuntimeError("Agent 上下文未初始化，请先调用 init_agent_context()")


@tool
def search_notes(query: str) -> str:
    """根据语义搜索当前用户的笔记，返回相关笔记的 ID 和标题列表。"""
    _ensure_context()
    docs = _VECTORSTORE.similarity_search_with_score(
        query,
        k=3,
        filter={"user_id": str(_CURRENT_USER_ID)},
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
    _ensure_context()
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
    _ensure_context()
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
        return "\n".join(
            f"ID: {n[0]} 标题: {n[1]} 时间: {n[2]}" for n in notes
        )
    except Exception as e:
        return f"查询失败：{e}"


def build_agent():
    """
    构建一个 ReAct 风格的 Tool-Calling Agent：
    - LLM 使用 DeepSeek（从环境变量读取 key / base_url / model）
    - 工具有：search_notes / get_note_detail / get_note_list
    - 返回值支持 astream，main.py 已按官方写法消费 chunk["agent"] / chunk["tools"]
    """
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
    )

    system_prompt = SystemMessage(
        content=(
            "你是用户的私人知识与写作助手，能够查看 TA 的所有笔记并进行：\n"
            "1）根据需求搜索相关笔记\n"
            "2）阅读某条笔记的详细内容\n"
            "3）汇总、改写、生成新的内容\n"
            "回答时要：\n"
            "- 尽量引用具体笔记（ID/标题）\n"
            "- 明确哪些是来自笔记的事实，哪些是你的推理或建议\n"
            "- 语言自然、有条理，适合直接复制到笔记里使用。"
        )
    )

    return create_agent(
        llm=llm,
        tools=[search_notes, get_note_detail, get_note_list],
        system_prompt=system_prompt,
    )
