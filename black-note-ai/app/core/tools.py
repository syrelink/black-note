"""
app/core/tools.py

LangGraph 工具集（3 个）：
  1. search_notes   — Agentic RAG：Query Rewriting + BM25+Qdrant混合检索 + CRAG Grader
  2. get_note       — 按 ID 精确读取完整笔记（MongoDB）
  3. get_note_stats — 聚合统计（MongoDB）
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Literal

from langchain.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.rag import make_rag_retriever, rerank_docs


# ── 结构化输出 Schema ─────────────────────────────────────────────

class GradeDocs(BaseModel):
    """CRAG Grader：批量判断每篇文档是否与问题相关"""
    scores: list[Literal["yes", "no"]]

class RewrittenQuery(BaseModel):
    """Query Rewriter：将自然语言问题改写为检索关键词"""
    query: str


def make_tools(vectorstore):

    # ── 轻量 LLM（temperature=0，用于 Grader 和 Rewriter）─────────
    _llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0,
    )
    grader_llm   = _llm.with_structured_output(GradeDocs)
    rewriter_llm = _llm.with_structured_output(RewrittenQuery)

    MAX_RETRIES  = 2  # 最多重试次数
    MIN_RELEVANT = 2  # 相关文档达到这个数才认为检索成功

    # ── 工具 1：Agentic RAG（CRAG + Query Rewriting）──────────────
    @tool
    async def search_notes(
        query: str,
        limit: int = 6,
        config: RunnableConfig = None,
    ) -> str:
        """
        用自然语言语义检索用户的笔记。内部自动执行查询改写和相关性验证（CRAG）。

        参数：
        - query: 用户的自然语言描述或关键词
        - limit: 最多返回条数（默认 6）

        返回：JSON，包含 notes 数组（note_id、title、created_at、snippet）和 total。
        """
        user_id = config.get("configurable", {}).get("user_id")
        current_query = query

        try:
            retriever  = make_rag_retriever(vectorstore, user_id=user_id)
            final_docs = []

            for attempt in range(MAX_RETRIES + 1):

                # ── Step 1：Query Rewriting（第二次起才改写）────────
                if attempt > 0:
                    rewrite_result = await rewriter_llm.ainvoke([
                        SystemMessage(content=(
                            "将用户问题改写为更适合中文向量检索的关键词组合。"
                            "只返回改写后的查询字符串，不要解释，不要标点。"
                        )),
                        HumanMessage(content=f"原始问题：{query}"),
                    ])
                    current_query = rewrite_result.query

                # ── Step 2：混合检索 + FlashRank 重排序 ─────────────
                raw_docs = await retriever.ainvoke(current_query)
                # FlashRank 是 CPU 密集型模型推理，保留 to_thread
                reranked = await asyncio.to_thread(rerank_docs, current_query, raw_docs, top_n=limit)

                if not reranked:
                    continue

                # ── Step 3：CRAG Grader（1次LLM调用批量打分）────────
                docs_text = "\n\n".join([
                    f"[文档{i + 1}]: {doc.page_content[:400]}"
                    for i, doc in enumerate(reranked)
                ])
                grade_result = await grader_llm.ainvoke([
                    SystemMessage(content=(
                        "你是文档相关性评分助手。\n"
                        "判断每篇文档是否与用户问题相关，返回与文档数量相同的 scores 列表，\n"
                        "每项为 'yes'（相关）或 'no'（不相关）。"
                    )),
                    HumanMessage(content=f"问题：{query}\n\n{docs_text}"),
                ])

                # 对齐长度，防止 LLM 返回数量不匹配
                scores   = (grade_result.scores + ["no"] * len(reranked))[:len(reranked)]
                relevant = [doc for doc, s in zip(reranked, scores) if s == "yes"]

                # ── Step 4：判断是否够用 ─────────────────────────────
                # 相关文档足够，或已到最后一次重试 → 结束循环
                if len(relevant) >= MIN_RELEVANT or attempt == MAX_RETRIES:
                    # 如果 grader 全判不相关，兜底返回 reranked 前3篇
                    final_docs = relevant if relevant else reranked[:3]
                    break
                # 否则进入下一轮，带改写重试

            # ── 构建返回结果 ─────────────────────────────────────────
            seen, notes = set(), []
            for doc in final_docs:
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
            return json.dumps({"error": f"检索失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 2：按 ID 读取完整笔记 ─────────────────────────────────
    @tool
    async def get_note(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        按笔记 ID 从 MongoDB 读取完整内容。search_notes 只返回摘要，
        需要阅读全文时调用此工具。

        参数：
        - note_id: 笔记唯一 ID（来自 search_notes 的返回结果）

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

    # ── 工具 3：聚合统计 ─────────────────────────────────────────────
    @tool
    async def get_note_stats(config: RunnableConfig = None) -> str:
        """
        获取用户笔记的聚合统计数据：总篇数、最新一篇时间、近30天新增数。
        适用于"我写了多少笔记"、"这个月写了几篇"等统计类问题。

        返回：JSON，包含 total、latest、this_month。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            from bson import ObjectId
            from app.database import get_motor_client
            from app.config import settings

            db        = get_motor_client()[settings.MONGODB_DB]
            now       = datetime.utcnow()
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

    tools = [search_notes, get_note, get_note_stats]
    tools_by_name = {t.name: t for t in tools}
    return tools, tools_by_name
