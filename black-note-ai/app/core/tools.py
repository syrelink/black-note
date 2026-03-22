"""
app/core/tools.py - 重构版 v6.0

重构原则：
    工具 = LLM 自己做不到、必须借助外部的原子操作
    每个工具对应一个数据源 + 一种查询方式，不承载任何分析意图

删除的工具：
    - cross_note_analysis     → 与 semantic_search_notes 底层完全相同，合并
    - professional_note_review → 与 get_note_content 底层完全相同，合并

保留的工具（3个）：
    1. search_notes       向量库语义检索（LLM 做不到的模糊匹配）
    2. get_note           MySQL 按 ID 精确读取完整笔记
    3. get_note_stats     MySQL 聚合统计

分析、总结、审阅、串联规律 —— 这些都是 LLM 的推理行为，在 system prompt 里指导即可，
不需要用额外工具来"包装意图"。
"""

import os
import json
from typing import List

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from sqlalchemy import create_engine, text

from app.core.rag import make_rag_retriever, rerank_docs

load_dotenv()

_ENGINE = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@localhost/black_note"),
    pool_size=5,
    max_overflow=10,
)


def make_tools(vectorstore):
    """
    工具工厂函数，启动时调用一次。
    返回 (tools_list, tools_by_name)。
    """
    rag_retriever = make_rag_retriever(vectorstore)

    # ── 工具 1：向量语义检索 ───────────────────────────────────────────────
    # 存在理由：向量相似度检索 + rerank 是 LLM 自身做不到的外部能力。
    # 原来的 cross_note_analysis 与本工具底层逻辑 100% 相同（同一数据源、同一调用链），
    # 唯一差异只是 limit 默认值和字段名，这些用参数解决即可，不需要两个工具。
    # "分析规律""串联主题"是 LLM 拿到数据后自己推理的事，不属于工具职责。
    @tool
    def search_notes(
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

        注意：本工具只负责检索，后续的总结、分析、审阅由 LLM 自行完成。
        """
        user_id = config.get("configurable", {}).get("user_id")
        try:
            raw_docs: List = rag_retriever.invoke(query)

            # 只保留当前用户且未删除的文档
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
                        "note_id": note_id,
                        "title": meta.get("title", "无标题"),
                        "created_at": str(meta.get("created_at", "")),
                        # snippet 用于快速预览，LLM 可据此决定是否需要调用 get_note 读完整内容
                        "snippet": doc.page_content[:400] + "..." if len(doc.page_content) > 400 else doc.page_content,
                        "images": meta.get("images"),
                    })

            return json.dumps({"notes": notes, "total": len(notes)}, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"语义检索失败：{str(e)}"}, ensure_ascii=False)

    # ── 工具 2：按 ID 读取完整笔记 ────────────────────────────────────────
    # 存在理由：search_notes 返回的是向量切片（snippet），当 LLM 需要笔记完整原文时
    # （如审阅、精读、引用），必须回到 MySQL 按主键精确查询。
    # 原来的 professional_note_review 与本工具完全相同，"专业审阅"是 LLM 的推理行为，
    # 用 system prompt 指导即可，不需要单独封装成工具。
    @tool
    def get_note(
        note_id: str,
        config: RunnableConfig = None,
    ) -> str:
        """
        按笔记 ID 从数据库读取完整内容。

        参数：
        - note_id: 笔记唯一 ID（通常来自 search_notes 的返回结果）

        返回：JSON，包含 note_id、title、content（完整正文）、created_at、images。

        典型调用链：search_notes 找到候选笔记 → get_note 读取完整内容 → LLM 进行分析/审阅。
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

    # ── 工具 3：聚合统计 ──────────────────────────────────────────────────
    # 存在理由：COUNT / MAX 这类聚合查询既不是向量检索（工具1），
    # 也不是按 ID 精确读取（工具2），是独立的数据源访问方式，保留为单独工具。
    @tool
    def get_note_stats(config: RunnableConfig = None) -> str:
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

    # ── 导出 ──────────────────────────────────────────────────────────────
    tools = [search_notes, get_note, get_note_stats]
    tools_by_name = {t.name: t for t in tools}

    return tools, tools_by_name