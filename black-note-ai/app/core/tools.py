"""
app/core/tools.py

LangGraph 工具集（3 个）：
  1. search_notes    — 向量语义检索
  2. get_note        — 按 ID 精确读取完整笔记（MongoDB）
  3. get_all_titles  — 全量标题列表（MongoDB）
  4. get_note_stats  — 聚合统计（MongoDB）
"""

import asyncio
import json
from datetime import datetime, timedelta

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from app.core.rag import make_rag_retriever, rerank_docs


def make_tools(vectorstore):

    # ── 工具 1：向量语义检索 ────────────────────────────────────────
    @tool
    async def search_notes(
        query: str,
        limit: int = 8,
        config: RunnableConfig = None,
    ) -> str:
        """
        用自然语言语义检索用户的笔记。

        参数：
        - query: 用户的模糊描述或关键词
        - limit: 返回条数（默认 8）

        返回：JSON，包含 notes 数组（note_id、title、created_at、snippet）和 total。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            retriever = make_rag_retriever(vectorstore, user_id=user_id)
            raw_docs  = await asyncio.to_thread(retriever.invoke, query)
            reranked  = await asyncio.to_thread(rerank_docs, query, raw_docs, top_n=limit)

            seen, notes = set(), []
            for doc in reranked:
                note_id = doc.metadata.get("note_id")
                if note_id and note_id not in seen:
                    seen.add(note_id)
                    meta = doc.metadata
                    notes.append({
                        "note_id":    note_id,
                        "title":      meta.get("title", "无标题"),
                        "created_at": str(meta.get("created_at", "")),
                        "snippet":    doc.page_content[:400] + "..." if len(doc.page_content) > 400 else doc.page_content,
                    })
            return json.dumps({"notes": notes, "total": len(notes)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"语义检索失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 2：按 ID 读取完整笔记 ─────────────────────────────────
    @tool
    async def get_note(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        按笔记 ID 从 MongoDB 读取完整内容。

        参数：
        - note_id: 笔记唯一 ID（通常来自 search_notes 的返回结果）

        返回：JSON，包含 note_id、title、content、created_at、images。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            from bson import ObjectId
            from app.database import get_motor_client
            from app.config import settings

            db   = get_motor_client()[settings.MONGODB_DB]
            note = await db.notes.find_one({
                "_id":        ObjectId(note_id),
                "user_id":    ObjectId(user_id),
                "is_deleted": False,
            })
            if not note:
                return json.dumps({"error": f"笔记 {note_id} 不存在或无权访问"}, ensure_ascii=False)

            return json.dumps({
                "note_id":    note_id,
                "title":      note.get("title"),
                "content":    note.get("content"),
                "created_at": str(note.get("created_at", "")),
                "images":     note.get("images", []),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"读取失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 3：全量标题列表 ─────────────────────────────────────────
    @tool
    async def get_all_titles(config: RunnableConfig = None) -> str:
        """
        获取用户所有笔记的标题列表、创建时间、获赞数，按创建时间倒序排列。

        返回：JSON，包含 notes 数组（note_id、title、created_at、like_count）和 total。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            from bson import ObjectId
            from app.database import get_motor_client
            from app.config import settings

            db    = get_motor_client()[settings.MONGODB_DB]
            cursor = db.notes.find(
                {"user_id": ObjectId(user_id), "is_deleted": False},
                {"title": 1, "created_at": 1, "like_count": 1},
                sort=[("created_at", -1)],
            )
            rows = await cursor.to_list(None)
            notes = [
                {
                    "note_id":    str(r["_id"]),
                    "title":      r.get("title"),
                    "created_at": str(r.get("created_at", "")),
                    "like_count": r.get("like_count", 0),
                }
                for r in rows
            ]
            return json.dumps({"notes": notes, "total": len(notes)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"获取标题失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 4：聚合统计 ─────────────────────────────────────────────
    @tool
    async def get_note_stats(config: RunnableConfig = None) -> str:
        """
        获取用户笔记的聚合统计数据（总数、最近一篇创建时间、近 30 天数量）。

        返回：JSON，包含 total、latest、this_month。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            from bson import ObjectId
            from app.database import get_motor_client
            from app.config import settings

            db      = get_motor_client()[settings.MONGODB_DB]
            now     = datetime.utcnow()
            month_ago = now - timedelta(days=30)

            pipeline = [
                {"$match": {"user_id": ObjectId(user_id), "is_deleted": False}},
                {"$group": {
                    "_id":        None,
                    "total":      {"$sum": 1},
                    "latest":     {"$max": "$created_at"},
                    "this_month": {"$sum": {"$cond": [{"$gte": ["$created_at", month_ago]}, 1, 0]}},
                }},
            ]
            result = await db.notes.aggregate(pipeline).to_list(1)
            if not result:
                return json.dumps({"total": 0, "latest": None, "this_month": 0}, ensure_ascii=False)
            row = result[0]
            return json.dumps({
                "total":      row["total"],
                "latest":     str(row["latest"]) if row["latest"] else None,
                "this_month": row["this_month"],
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"统计失败：{str(e)}"}, ensure_ascii=False)

    tools = [search_notes, get_note, get_all_titles, get_note_stats]
    tools_by_name = {t.name: t for t in tools}
    return tools, tools_by_name
