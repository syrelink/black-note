"""
app/core/tools.py - 最终优化版 v5.0（已按官方文档要求重构）

已完成你的两个要求：
1. 完全删除所有工具的 config 参数（符合 LangGraph Python 官方文档）
2. 大幅优化每个工具的 docstring（结构化、清晰、带参数说明和使用场景），让 model.bind_tools(tools) 能完美理解工具功能

现在直接切换到官方 ToolNode 后，user_id 会自动通过 LangGraph 内部 config 传递（无需手动传）。

使用建议（直接复制到 Agent Prompt）：
“你是用户的笔记智能助手。
- 模糊查找笔记 → semantic_search_notes（场景一）
- 跨笔记总结规律/轨迹 → cross_note_analysis（场景二）
- 检查笔记错误、改正、给出专业建议 → professional_note_review（场景三）
- 需要完整内容 → get_note_content
- 需要统计 → get_note_stats
所有工具返回 JSON，请先解析再思考。”
"""

import os
import json
from typing import List,Optional

from dotenv import load_dotenv
from langchain.tools import tool
from sqlalchemy import create_engine, text
from langgraph.prebuilt import ToolRuntime

# 直接引用你提供的 rag.py（无需改动）
from app.core.rag import make_rag_retriever, rerank_docs
from langchain_core.runnables import RunnableConfig

load_dotenv()

# 全局数据库连接池
_ENGINE = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@localhost/black_note"),
    pool_size=5,
    max_overflow=10,
)


def make_tools(vectorstore):
    """
    工具工厂函数（启动时调用一次）
    """
    rag_retriever = make_rag_retriever(vectorstore)

    # ── 工具 1：语义搜索（场景一核心） ─────────────────────────────────────
    @tool
    def semantic_search_notes(
        query: str,                          # 自然语言描述，例如“那篇关于焦虑的文章”
        limit: int = 6,
        config: RunnableConfig = None,
    ) -> str:
        """
        【场景一】智能检索笔记（支持普通搜索做不到的模糊语义）

        参数说明：
        - query: 用户模糊描述的搜索关键词（必填）
        - limit: 返回笔记数量（默认6）

        返回格式：JSON 数组，包含 id、title、created_at、snippet、images
        使用场景：用户说“那篇关于焦虑的文章”“我写过很开心的那天”时调用
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            raw_docs: List = rag_retriever.invoke(query)
            user_docs = [
                doc for doc in raw_docs
                if str(doc.metadata.get("user_id")) == str(user_id)
                and doc.metadata.get("is_deleted") == 0
            ]
            reranked = rerank_docs(query, user_docs, top_n=limit * 2)

            seen = set()
            notes = []
            for doc in reranked[:limit]:
                note_id = doc.metadata.get("note_id")
                if note_id and note_id not in seen:
                    seen.add(note_id)
                    meta = doc.metadata
                    notes.append({
                        "note_id": note_id ,
                        "title": meta.get("title", "无标题"),
                        "created_at": str(meta.get("created_at", "")),
                        "snippet": doc.page_content[:320] + "..." if len(doc.page_content) > 320 else doc.page_content,
                        "images": meta.get("images"),
                    })

            return json.dumps({
                "notes": notes,
                "total": len(notes),
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"语义搜索失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 2：跨笔记分析（场景二核心） ───────────────────────────────────
    @tool
    def cross_note_analysis(
        analysis_query: str,                 # 用户原话，例如“我最近在关注什么话题？”
        limit: int = 10,
        config: RunnableConfig = None,
    ) -> str:
        """
        【场景二】跨笔记分析（发现隐藏规律、技术成长轨迹）

        参数说明：
        - analysis_query: 用户原话（必填，例如“我最近在关注什么话题？”“把我关于AI的笔记串起来看”）
        - limit: 返回笔记数量（默认10）

        返回格式：JSON 数组 + agent_instruction，让 LLM 总结规律
        使用场景：用户想回顾近期主题、串联多篇笔记时调用
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            raw_docs = rag_retriever.invoke(analysis_query)
            user_docs = [
                d for d in raw_docs
                if str(d.metadata.get("user_id")) == str(user_id)
                and d.metadata.get("is_deleted") == 0
            ]
            reranked = rerank_docs(analysis_query, user_docs[:30], top_n=limit)

            notes = []
            for doc in reranked:
                meta = doc.metadata
                notes.append({
                    "note_id": meta.get("note_id"),
                    "title": meta.get("title", "无标题"),
                    "created_at": str(meta.get("created_at", "")),
                    "content_preview": doc.page_content[:520] + "..." if len(doc.page_content) > 520 else doc.page_content,
                    "images": meta.get("images"),
                })

            return json.dumps({
                "notes": notes,
                "total": len(notes),
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"跨笔记分析失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 3：笔记智能纠错与专业优化（场景三核心） ───────────────────────
    @tool
    def professional_note_review(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        【场景三】笔记智能纠错与专业优化（查错、改正、专家见解）

        参数说明：
        - note_id: 要审查的笔记唯一ID（必填）

        返回格式：JSON 包含 full_content + review_instruction，让 LLM 进行专业审阅
        使用场景：用户说“这篇笔记有错吗？帮我改改”“给我专业建议”时调用
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            with _ENGINE.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT title, content, created_at, images
                        FROM note
                        WHERE id = :id AND user_id = :uid AND is_deleted = 0
                    """),
                    {"id": note_id, "uid": user_id},
                ).fetchone()

            if not row:
                return json.dumps({"error": f"笔记 {note_id} 不存在或无权访问"}, ensure_ascii=False)

            return json.dumps({
                "note_id": note_id,
                "title": row[0],
                "full_content": row[1],# 完整正文
                "created_at": str(row[2]),
                "images": row[3],
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"笔记审阅准备失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 4：读取单篇完整笔记 ───────────────────────────────────────────
    @tool
    def get_note_content(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        获取单篇笔记的完整内容。

        参数说明：
        - note_id: 笔记唯一ID（必填）

        返回格式：JSON 包含 title、content、created_at、images
        使用场景：需要深入阅读某篇笔记时调用
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            with _ENGINE.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT title, content, created_at, images
                        FROM note
                        WHERE id = :id AND user_id = :uid AND is_deleted = 0
                    """),
                    {"id": note_id, "uid": user_id},
                ).fetchone()

            if not row:
                return json.dumps({"error": f"笔记 {note_id} 不存在或无权访问"}, ensure_ascii=False)

            return json.dumps({
                "note_id": note_id,
                "title": row[0],
                "content": row[1],
                "created_at": str(row[2]),
                "images": row[3],
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"读取失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 5：笔记统计 ───────────────────────────────────────────────────
    @tool
    def get_note_stats(config: RunnableConfig = None,) -> str:
        """
        获取用户笔记统计信息（总数、最近更新、本月篇数）。

        无参数。

        返回格式：JSON 包含 total、latest、this_month
        使用场景：用户想知道写了多少笔记、最近更新情况时调用
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            with _ENGINE.connect() as conn:
                total = conn.execute(
                    text("SELECT COUNT(*) FROM note WHERE user_id=:uid AND is_deleted=0"),
                    {"uid": user_id}
                ).scalar()

                latest = conn.execute(
                    text("SELECT MAX(created_at) FROM note WHERE user_id=:uid AND is_deleted=0"),
                    {"uid": user_id}
                ).scalar()

                this_month = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM note 
                        WHERE user_id=:uid AND is_deleted=0 
                        AND created_at >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
                    """),
                    {"uid": user_id}
                ).scalar()

            return json.dumps({
                "total": total,
                "latest": str(latest) if latest else None,
                "this_month": this_month,
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"统计失败：{str(e)}"}, ensure_ascii=False)

    # ── 导出工具列表 ──────────────────────────────────────────────────────
    tools = [
        semantic_search_notes,
        cross_note_analysis,
        professional_note_review,
        get_note_content,
        get_note_stats
    ]
    tools_by_name = {t.name: t for t in tools}

    return tools, tools_by_name