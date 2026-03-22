"""
app/core/tools.py - 重构版 v6.1（全异步）

重构原则：
    工具 = LLM 自己做不到、必须借助外部的原子操作
    每个工具对应一个数据源 + 一种查询方式，不承载任何分析意图

v6.1 相对 v6.0 的变化：
    - 数据库引擎从同步 create_engine (pymysql) 换成异步 create_async_engine (aiomysql)
    - 所有工具函数改为 async def
    - MySQL I/O 改为 await conn.execute(...)
    - 向量检索（rag_retriever.invoke）用 asyncio.to_thread 包装，
      保持与同步向量库的兼容性（如向量库已支持 ainvoke 可直接替换）

依赖变化：
    pip install aiomysql sqlalchemy[asyncio]
    （移除 pymysql，或保留供其他模块使用）

保留的工具（3个）：
    1. search_notes   向量库语义检索（LLM 做不到的模糊匹配）
    2. get_note       MySQL 按 ID 精确读取完整笔记
    3. get_note_stats MySQL 聚合统计

分析、总结、审阅、串联规律 —— 这些都是 LLM 的推理行为，在 system prompt 里指导即可，
不需要用额外工具来"包装意图"。
"""

import asyncio
import json
import os
from typing import List

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.rag import make_rag_retriever, rerank_docs

load_dotenv()

# ── 异步引擎 ──────────────────────────────────────────────────────────────
# 驱动从 pymysql 换成 aiomysql，URL scheme 改为 mysql+aiomysql://
# 依赖：pip install aiomysql sqlalchemy[asyncio]
_ASYNC_ENGINE = create_async_engine(
    os.getenv(
        "MYSQL_ASYNC_URL",
        "mysql+aiomysql://root:123456@localhost/black_note",
    ),
    pool_size=5,
    max_overflow=10,
    # echo=True,  # 调试时可开启，打印 SQL
)


def make_tools(vectorstore):
    """
    工具工厂函数，启动时调用一次。
    返回 (tools_list, tools_by_name)。
    """
    rag_retriever = make_rag_retriever(vectorstore)

    # ── 工具 1：向量语义检索 ───────────────────────────────────────────────
    # 向量库当前只提供同步 invoke，用 asyncio.to_thread 放入线程池，
    # 避免阻塞 event loop。若向量库升级支持 ainvoke，可直接替换为：
    #   raw_docs = await rag_retriever.ainvoke(query)
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
            # 同步向量库放入线程池，避免阻塞 event loop
            raw_docs: List = await asyncio.to_thread(rag_retriever.invoke, query)

            # 只保留当前用户且未删除的文档
            user_docs = [
                doc for doc in raw_docs
                if str(doc.metadata.get("user_id")) == str(user_id)
                and doc.metadata.get("is_deleted") == 0
            ]

            # rerank 也是 CPU 密集型同步操作，同样放入线程池
            reranked = await asyncio.to_thread(rerank_docs, query, user_docs, limit * 2)

            seen = set()
            notes = []
            for doc in reranked[:limit]:
                note_id = doc.metadata.get("note_id")
                if note_id and note_id not in seen:
                    seen.add(note_id)
                    meta = doc.metadata
                    notes.append({
                        "note_id": note_id,
                        "title": meta.get("title", "无标题"),
                        "created_at": str(meta.get("created_at", "")),
                        # snippet 用于快速预览，LLM 可据此决定是否需要调用 get_note 读完整内容
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
                    "note_id": note_id,
                    "title": row[0],
                    "content": row[1],
                    "created_at": str(row[2]),
                    "images": row[3],
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
                total = (
                    await conn.execute(
                        text("SELECT COUNT(*) FROM note WHERE user_id=:uid AND is_deleted=0"),
                        {"uid": user_id},
                    )
                ).scalar()

                latest = (
                    await conn.execute(
                        text("SELECT MAX(created_at) FROM note WHERE user_id=:uid AND is_deleted=0"),
                        {"uid": user_id},
                    )
                ).scalar()

                this_month = (
                    await conn.execute(
                        text("""
                            SELECT COUNT(*) FROM note
                            WHERE user_id=:uid AND is_deleted=0
                            AND created_at >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
                        """),
                        {"uid": user_id},
                    )
                ).scalar()

            return json.dumps(
                {
                    "total": total,
                    "latest": str(latest) if latest else None,
                    "this_month": this_month,
                },
                ensure_ascii=False,
            )

        except Exception as e:
            return json.dumps({"error": f"统计失败：{str(e)}"}, ensure_ascii=False)

    # ── 导出 ──────────────────────────────────────────────────────────────
    tools = [search_notes, get_note, get_note_stats]
    tools_by_name = {t.name: t for t in tools}

    return tools, tools_by_name