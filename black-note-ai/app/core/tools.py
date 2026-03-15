"""
app/core/tools.py

按照官方文档 Quickstart 的工具写法：
  from langchain.tools import tool
  @tool
  def func(args) -> type:
      ...

文档关键变化：
  - 导入从 langchain.tools 来，不再是 langchain_core.tools
  - 文档示例里用 tools_by_name = {tool.name: tool for tool in tools}
    在 tool_node 里手动查找执行，不再依赖 ToolNode
  - 工具函数本身保持纯粹，user_id 通过 config 注入（RunnableConfig）
"""

import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import create_engine, text

from app.core.rag import make_rag_retriever, rerank_docs

load_dotenv()

_engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)


def _get_user_id(config: RunnableConfig) -> str | None:
    """从 config 中安全地取出 user_id"""
    return (config or {}).get("configurable", {}).get("user_id")


def _parse_time_range(time_range: str | None) -> tuple[datetime | None, datetime | None]:
    """
    解析时间范围字符串 → (start, end)
    支持："7d" / "30d" / "2024-03"
    """
    if not time_range:
        return None, None
    now = datetime.now()
    if time_range.endswith("d"):
        days = int(time_range[:-1])
        return now - timedelta(days=days), now
    if len(time_range) == 7 and "-" in time_range:
        year, month = map(int, time_range.split("-"))
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        return start, end
    return None, None


def make_tools(vectorstore):
    """
    工具工厂。只在应用启动时调用一次。
    返回工具列表和 tools_by_name 字典（文档写法，供 tool_node 使用）。
    """

    rag_retriever = make_rag_retriever(vectorstore)

    # ── 工具1：语义搜索 ───────────────────────────────────
    @tool
    def search_notes(
        query: str,
        time_range: str = None,
        config: RunnableConfig = None,
    ) -> str:
        """
        语义搜索用户笔记，支持模糊表达和关键词匹配。

        Args:
            query: 搜索内容，例如"关于焦虑的文章"、"Python 异步"
            time_range: 可选时间范围，"7d"最近7天，"30d"最近30天，"2024-03"某年月
        """
        user_id = _get_user_id(config)
        if not user_id:
            return json.dumps({"error": "未获取到用户ID"}, ensure_ascii=False)
        try:
            raw_docs = rag_retriever.invoke(query)
            user_docs = [d for d in raw_docs if d.metadata.get("user_id") == user_id]
            start, end = _parse_time_range(time_range)
            if start and end:
                user_docs = [
                    d for d in user_docs
                    if start <= datetime.fromisoformat(
                        str(d.metadata.get("created_at", "2000-01-01"))
                    ) <= end
                ]
            if not user_docs:
                return json.dumps({"notes": [], "total": 0}, ensure_ascii=False)
            reranked = rerank_docs(query, user_docs, top_n=6)
            seen, unique = set(), []
            for doc in reranked:
                nid = doc.metadata.get("note_id")
                if nid and nid not in seen:
                    seen.add(nid)
                    unique.append(doc)
            return json.dumps({
                "notes": [
                    {
                        "note_id": d.metadata.get("note_id"),
                        "title":   d.metadata.get("title", "无标题"),
                        "snippet": d.page_content[:300] + ("..." if len(d.page_content) > 300 else ""),
                    }
                    for d in unique
                ],
                "total": len(unique),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 工具2：读取全文 ───────────────────────────────────
    @tool
    def get_note_content(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        根据笔记 ID 读取完整笔记内容。
        通常在 search_notes 找到目标后，用户想看全文时调用。

        Args:
            note_id: 笔记的唯一 ID
        """
        user_id = _get_user_id(config)
        if not user_id:
            return json.dumps({"error": "未获取到用户ID"}, ensure_ascii=False)
        try:
            with _engine.connect() as conn:
                row = conn.execute(
                    text("SELECT title, content, created_at FROM note "
                         "WHERE id = :id AND user_id = :uid AND is_deleted = 0"),
                    {"id": note_id, "uid": user_id},
                ).fetchone()
            if not row:
                return json.dumps({"error": f"笔记 {note_id} 不存在或无权访问"}, ensure_ascii=False)
            return json.dumps(
                {"note_id": note_id, "title": row[0], "content": row[1], "created_at": str(row[2])},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 工具3：批量分析 ───────────────────────────────────
    @tool
    def analyze_notes(
        topic: str = None,
        time_range: str = None,
        limit: int = 20,
        config: RunnableConfig = None,
    ) -> str:
        """
        批量获取笔记原始数据，供 LLM 做跨笔记分析和总结。

        Args:
            topic: 可选，按主题语义召回；为空时返回最近 N 篇
            time_range: 可选时间范围，"7d"/"30d"/"2024-03"
            limit: 最多返回几篇，默认 20
        """
        user_id = _get_user_id(config)
        if not user_id:
            return json.dumps({"error": "未获取到用户ID"}, ensure_ascii=False)
        try:
            start, end = _parse_time_range(time_range)
            if topic:
                raw_docs = rag_retriever.invoke(topic)
                docs = [d for d in raw_docs if d.metadata.get("user_id") == user_id]
                if start and end:
                    docs = [
                        d for d in docs
                        if start <= datetime.fromisoformat(
                            str(d.metadata.get("created_at", "2000-01-01"))
                        ) <= end
                    ]
                seen, notes = set(), []
                for d in docs:
                    nid = d.metadata.get("note_id")
                    if nid and nid not in seen:
                        seen.add(nid)
                        notes.append({
                            "note_id":    nid,
                            "title":      d.metadata.get("title", "无标题"),
                            "created_at": str(d.metadata.get("created_at", "")),
                            "content":    d.page_content[:500],
                        })
                    if len(notes) >= limit:
                        break
            else:
                sql = ("SELECT id, title, content, created_at FROM note "
                       "WHERE user_id = :uid AND is_deleted = 0")
                params: dict = {"uid": user_id}
                if start and end:
                    sql += " AND created_at BETWEEN :start AND :end"
                    params.update({"start": start, "end": end})
                sql += " ORDER BY created_at DESC LIMIT :limit"
                params["limit"] = limit
                with _engine.connect() as conn:
                    rows = conn.execute(text(sql), params).fetchall()
                notes = [
                    {"note_id": str(r[0]), "title": r[1],
                     "created_at": str(r[3]), "content": (r[2] or "")[:500]}
                    for r in rows
                ]
            return json.dumps({"notes": notes, "total": len(notes)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ── 工具4：写作统计 ───────────────────────────────────
    @tool
    def get_note_stats(config: RunnableConfig = None) -> str:
        """
        获取写作统计：总篇数、最近活跃时间、本周/本月篇数。
        适用场景："我写了多少笔记"、"我有没有坚持写作"
        """
        user_id = _get_user_id(config)
        if not user_id:
            return json.dumps({"error": "未获取到用户ID"}, ensure_ascii=False)
        try:
            now = datetime.now()
            week_start  = now - timedelta(days=now.weekday())
            month_start = now.replace(day=1)
            with _engine.connect() as conn:
                total      = conn.execute(text("SELECT COUNT(*) FROM note WHERE user_id=:uid AND is_deleted=0"), {"uid": user_id}).scalar()
                latest     = conn.execute(text("SELECT MAX(created_at) FROM note WHERE user_id=:uid AND is_deleted=0"), {"uid": user_id}).scalar()
                this_week  = conn.execute(text("SELECT COUNT(*) FROM note WHERE user_id=:uid AND is_deleted=0 AND created_at>=:ws"), {"uid": user_id, "ws": week_start}).scalar()
                this_month = conn.execute(text("SELECT COUNT(*) FROM note WHERE user_id=:uid AND is_deleted=0 AND created_at>=:ms"), {"uid": user_id, "ms": month_start}).scalar()
            return json.dumps(
                {"total": total, "latest": str(latest) if latest else None,
                 "this_week": this_week, "this_month": this_month},
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    tools = [search_notes, get_note_content, analyze_notes, get_note_stats]
    
    # 文档写法：构建 name→tool 的字典，供 tool_node 手动查找
    tools_by_name = {t.name: t for t in tools}

    return tools, tools_by_name