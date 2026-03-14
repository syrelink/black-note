"""
app/tools.py
只负责工具定义和 make_tools 函数
所有 RAG 检索逻辑从 rag.py 导入
"""

from langchain_core.tools import tool
from app.core.rag import make_rag_tool   # ← 从 rag.py 导入

# MySQL 引擎（数据库工具共用）
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)


def make_tools(vectorstore, user_id: str):
    """唯一工具工厂函数，返回工具列表给 Agent 使用"""

    @tool
    def get_recent_notes(n: int = 5) -> str:
        """获取用户最近写的 N 篇笔记（只返回标题 + ID + 时间）"""
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "SELECT id, title, created_at FROM note "
                        "WHERE user_id = :user_id AND is_deleted = 0 "
                        "ORDER BY created_at DESC LIMIT :n"
                    ),
                    {"user_id": user_id, "n": n},
                )
                notes = result.fetchall()

            if not notes:
                return "暂无笔记"

            formatted = [f"**ID: {note[0]}** 《{note[1]}》 - 时间：{note[2]}" for note in notes]
            return "## 最近笔记\n\n" + "\n".join(formatted)
        except Exception as e:
            return f"查询失败：{str(e)}"

    @tool
    def get_note_detail(note_id: str) -> str:
        """根据笔记 ID 获取完整笔记内容（已明确标明标题和内容）"""
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

            return f"""## 笔记详情
                    **标题**：{note[0]}
                    **时间**：{note[2]}
                    **内容**：{note[1]}"""
        except Exception as e:
            return f"查询失败：{str(e)}"


    # RAG 工具（从 rag.py 获取）
    search_notes_rag = make_rag_tool(vectorstore, user_id)

    return [get_recent_notes, get_note_detail, search_notes_rag]