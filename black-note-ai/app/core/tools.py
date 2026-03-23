"""
app/core/tools.py - 重构版 v6.2

v6.2 相对 v6.1 的变化：
    - make_tools 删除启动时预构建检索器的逻辑
      原来：rag_retriever = make_rag_retriever(vectorstore)  ← 启动时执行，user_id 未知
      现在：检索器在 search_notes 被调用时才按 user_id 动态构建，结果由 _retriever_cache 缓存
    - search_notes 删除后置过滤逻辑（user_id / is_deleted 过滤已前置到检索器内部）

保留的工具（3个）：
    1. search_notes   向量库语义检索
    2. get_note       MySQL 按 ID 精确读取完整笔记
    3. get_note_stats MySQL 聚合统计
"""

import asyncio
import json
import os

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.rag import make_rag_retriever, rerank_docs

load_dotenv()

_ASYNC_ENGINE = create_async_engine(
    os.getenv(
        "MYSQL_ASYNC_URL",
        "mysql+aiomysql://root:123456@localhost/black_note",
    ),
    pool_size=5,
    max_overflow=10,
)


def make_tools(vectorstore):
    """
    工具工厂函数，启动时调用一次。

    注意：不在这里构建检索器。
    检索器依赖 user_id，启动时 user_id 未知，
    必须等请求进来才能按用户构建。
    vectorstore 引用传进来供工具函数闭包使用。
    """

    # ── 工具 1：向量语义检索 ───────────────────────────────────────────────
    @tool
    async def search_notes(
        query: str,
        limit: int = 8,
        config: RunnableConfig = None,
    ) -> str:
        """
        用自然语言语义检索用户的笔记。

        参数：
        - query: 用户的模糊描述或关键词，例如"那篇关于焦虑的文章""我写过很开心的那天"
        - limit: 返回条数（默认 8，可按需调大用于跨笔记分析场景）

        返回：JSON，包含 notes 数组（note_id、title、created_at、snippet、images）和 total。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            # 请求时才构建检索器，此时 user_id 已知
            # make_rag_retriever 内部有 _retriever_cache，同一用户只构建一次
            # 过滤（user_id + is_deleted）已前置到检索器内部，不需要后置过滤
            retriever = make_rag_retriever(vectorstore, user_id=user_id)

            # 同步检索放入线程池，避免阻塞 event loop
            raw_docs = await asyncio.to_thread(retriever.invoke, query)

            # rerank 是 CPU 密集型同步操作，同样放入线程池
            reranked = await asyncio.to_thread(
                rerank_docs, query, raw_docs, top_n=limit
            )

            seen = set()
            notes = []
            for doc in reranked:
                note_id = doc.metadata.get("note_id")
                if note_id and note_id not in seen:
                    seen.add(note_id)
                    meta = doc.metadata
                    notes.append({
                        "note_id":    note_id,
                        "title":      meta.get("title", "无标题"),
                        "created_at": str(meta.get("created_at", "")),
                        "snippet": (
                            doc.page_content[:400] + "..."
                            if len(doc.page_content) > 400
                            else doc.page_content
                        ),
                        "images": meta.get("images"),
                    })

            return json.dumps({"notes": notes, "total": len(notes)}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"语义检索失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 2：按 ID 读取完整笔记 ────────────────────────────────────────
    @tool
    async def get_note(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        按笔记 ID 从数据库读取完整内容。

        参数：
        - note_id: 笔记唯一 ID（通常来自 search_notes 的返回结果）

        返回：JSON，包含 note_id、title、content（完整正文）、created_at、images。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            async with _ASYNC_ENGINE.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT title, content, created_at, images
                        FROM note
                        WHERE id = :id AND user_id = :uid AND is_deleted = 0
                    """),
                    {"id": note_id, "uid": user_id},
                )
                row = result.fetchone()

            if not row:
                return json.dumps(
                    {"error": f"笔记 {note_id} 不存在或无权访问"},
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "note_id":    note_id,
                    "title":      row[0],
                    "content":    row[1],
                    "created_at": str(row[2]),
                    "images":     row[3],
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps({"error": f"读取失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 3：聚合统计 ──────────────────────────────────────────────────
    @tool
    async def get_note_stats(config: RunnableConfig = None) -> str:
        """
        获取用户笔记的聚合统计数据。

        无参数。

        返回：JSON，包含：
        - total: 笔记总数
        - latest: 最近一篇的创建时间
        - this_month: 近 30 天内的笔记数
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            async with _ASYNC_ENGINE.connect() as conn:
                row = (await conn.execute(
                    text("""
                        SELECT
                            COUNT(*)                                                  AS total,
                            MAX(created_at)                                           AS latest,
                            SUM(created_at >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)) AS this_month
                        FROM note
                        WHERE user_id=:uid AND is_deleted=0
                    """),
                    {"uid": user_id},
                )).fetchone()

            return json.dumps(
                {
                    "total":      row[0],
                    "latest":     str(row[1]) if row[1] else None,
                    "this_month": row[2],
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps({"error": f"统计失败：{str(e)}"}, ensure_ascii=False)

    # ── 导出 ──────────────────────────────────────────────────────────────
    tools = [search_notes, get_note, get_note_stats]
    tools_by_name = {t.name: t for t in tools}

    return tools, tools_by_name