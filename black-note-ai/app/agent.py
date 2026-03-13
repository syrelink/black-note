"""
私人笔记 Agent：整合 RAG + 精确工具
- 支持语义/关键词搜索笔记（RAG tool）
- 支持按 ID 读完整笔记、列出所有笔记
- 使用 DeepSeek LLM + 记忆
"""

import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, text
from app.rag import make_rag_tool

load_dotenv()

# MySQL 连接
engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)

# 全局记忆（服务重启前保留对话历史）
_checkpointer = InMemorySaver()


def make_tools(vectorstore, user_id: str):
    """工具工厂：闭包注入 user_id，确保多用户隔离"""

    @tool
    def get_note_detail(note_id: str) -> str:
        """根据笔记 ID 获取笔记完整内容（标题 + 时间 + 正文）。"""
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
            return f"查询失败：{str(e)}"

    @tool
    def get_note_list(_: str = "") -> str:
        """获取当前用户所有笔记的标题 + ID + 时间列表（按时间降序）。"""
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
            return f"查询失败：{str(e)}"

    # 新增 RAG 工具：高级问答 / 内容召回
    rag_tool = make_rag_tool(vectorstore, user_id)

    return [get_note_detail, get_note_list, rag_tool]


def build_agent(vectorstore, user_id: str, thread_id: str = None):
    """
    构建 Agent
    - thread_id 可用于区分同一用户的不同会话（默认用 user_id 作为 thread_id）
    """
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
        streaming=True,
    )

    tools = make_tools(vectorstore, user_id)

    # 增强系统提示：明确告诉 Agent 工具的使用场景
    system_prompt = SystemMessage(content="""你是用户的私人笔记智能助手。

你的核心任务是帮助用户回忆、查询、管理笔记内容。
可用工具：
- get_note_detail：根据 ID 读取完整笔记内容（用户指定 ID 时用）
- get_note_list：列出用户所有笔记（用户问“我有哪些笔记”时用）
- search_notes_rag：高级 RAG 搜索 + 内容召回（用户问“我之前记过什么关于XX的？”、“XX笔记里写了什么？”等模糊/内容相关问题时用，优先考虑）

优先级建议：
1. 如果用户问具体笔记 ID 或标题 → 用 get_note_detail 或 get_note_list
2. 如果用户问“我有没有记过XX”、“我对XX的看法” → 用 search_notes_rag
3. 先用 search_notes 找 ID，再用 get_note_detail 读全文（链式调用）

始终基于工具返回的事实回答，不要编造内容。
如果不确定或没找到相关笔记，直接说“笔记中暂无相关记录”。
""")

    # 使用 create_agent（LangChain 当前推荐方式）
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=_checkpointer,
    )

    # 如果想用 LangGraph 更高级控制（推荐长期迁移），可改成：
    # from langgraph.prebuilt import create_react_agent
    # 但当前 create_agent 已足够，且兼容记忆

    return agent