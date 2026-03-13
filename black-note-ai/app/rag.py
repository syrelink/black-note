"""
RAG 检索模块（稳定混合检索版）
- 使用 EnsembleRetriever (langchain-classic) 做 dense + BM25 混合
- 第二阶段使用 FlashRank 做 reranking
- 完全不依赖 Chroma 原生 hybrid_search，避免 API 不稳定问题
"""

import os
from typing import List

from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever   # ← 关键包

# FlashRank reranker（轻量、速度快、本地运行）
from flashrank import Ranker, RerankRequest

load_dotenv()


def build_retriever(vectorstore: Chroma, user_id: str) -> EnsembleRetriever:
    """
    构建混合检索器：
    1. Dense 向量检索（语义）
    2. BM25 关键词检索（精确匹配）
    3. EnsembleRetriever + RRF 融合
    """
    # Dense 检索器（Chroma 向量部分）
    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": 12,                        # 多召回一些给 rerank
            "filter": {"user_id": user_id}
        }
    )

    # BM25 检索器（从当前用户所有 chunk 构建）
    # 注意：这里每次都从 vectorstore 拉取用户所有文档构建 BM25
    # 如果用户文档非常多，可考虑缓存或预构建
    result = vectorstore.get(where={"user_id": user_id})
    raw_docs = result.get("documents", [])
    metadatas = result.get("metadatas", [])

    documents = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(raw_docs, metadatas)
    ]

    bm25_retriever = BM25Retriever.from_documents(
        documents,
        k=12
    )

    # Ensemble + RRF 融合（BM25 权重稍高，笔记场景关键词更重要）
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.48, 0.52],           # 可调：0.5:0.5 也很常见
        c=60                            # RRF 参数，越大越平滑
    )

    return ensemble_retriever


from typing import List
from langchain_core.documents import Document
from flashrank import Ranker, RerankRequest


def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """
    使用 FlashRank 对召回结果进行重排序（第二阶段精排）

    特点：
    - 严格过滤空/太短的 passage（避免 FlashRank 返回字符串错误）
    - 详细日志输出，便于定位问题
    - 异常时降级返回原始顺序的前 N 条
    - 支持 ms-marco-MiniLM-L-12-v2 等模型
    """
    if not docs:
        print("[Rerank] 输入 docs 为空，直接返回 []")
        return []

    query_clean = (query or "").strip()
    if not query_clean:
        print("[Rerank] query 为空，直接返回原始顺序前 {} 条".format(top_n))
        return docs[:top_n]

    # 过滤：只保留有意义的 passage（至少 10 个字符，可根据需要调整）
    passages = []
    valid_docs = []
    skipped_count = 0

    for doc in docs:
        content = (doc.page_content or "").strip()
        if len(content) >= 10:  # 过滤掉空行、纯空格、太短的 chunk
            passages.append(content)
            valid_docs.append(doc)
        else:
            skipped_count += 1
            # 可选：打印被跳过的内容，便于调试
            # print(f"[Rerank] 跳过短/空 passage: len={len(content)}, preview={repr(content[:40])}...")

    if skipped_count > 0:
        print(f"[Rerank] 跳过了 {skipped_count} 个空/短 passage（剩余 {len(passages)} 个有效）")

    if not passages:
        print("[Rerank] 无任何有效 passage，返回原始顺序前 {} 条".format(top_n))
        return docs[:top_n]

    try:
        print(f"[Rerank] 初始化 Ranker (model=ms-marco-MiniLM-L-12-v2)")
        ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

        request = RerankRequest(query=query_clean, passages=passages)
        print(f"[Rerank] 开始 rerank... (query长度={len(query_clean)}, passages数={len(passages)})")

        results = ranker.rerank(request)

        # 关键防御：检查返回类型
        if isinstance(results, str):
            print(f"[ERROR] FlashRank 返回字符串（非列表）: {repr(results)[:400]}")
            return valid_docs[:top_n]

        if not isinstance(results, (list, tuple)) or not results:
            print(f"[WARNING] FlashRank 返回空或非列表: type={type(results)}")
            return valid_docs[:top_n]

        if not isinstance(results[0], dict) or "score" not in results[0]:
            print(f"[WARNING] FlashRank 返回项格式异常: {repr(results[0])[:300]}")
            return valid_docs[:top_n]

        # 安全排序
        def safe_score(item):
            try:
                return float(item.get("score", 0))
            except:
                return 0.0

        sorted_indices = sorted(
            range(len(results)),
            key=lambda i: safe_score(results[i]),
            reverse=True
        )

        reranked = [valid_docs[i] for i in sorted_indices[:top_n] if i < len(valid_docs)]
        print(f"[Rerank] 重排成功，返回 {len(reranked)} 条")
        return reranked

    except Exception as e:
        print(f"[ERROR] FlashRank 执行异常: {type(e).__name__}: {str(e)}")
        # 可选：打印完整栈追踪（开发时开启）
        # import traceback
        # traceback.print_exc()
        return valid_docs[:top_n]

def make_rag_tool(vectorstore: Chroma, user_id: str):
    """
    把混合检索 + rerank 封装成 Tool，供 Agent 调用
    """
    retriever = build_retriever(vectorstore, user_id)

    @tool
    def search_notes_rag(query: str) -> str:
        """
        检索用户私人笔记库（混合检索 + 重排序）。
        支持语义 + 关键词匹配，适合问“我记过什么关于XX的？”等内容相关问题。
        """
        # 第一阶段：混合召回（多取一些）
        raw_docs = retriever.invoke(query)

        if not raw_docs:
            return "您的笔记中暂无相关内容。"
        print(f"[DEBUG] raw_docs count: {len(raw_docs)}, query: {query[:50]}...")
        # 第二阶段：rerank 重排序（核心提升点）
        reranked_docs = rerank_docs(query, raw_docs, top_n=7)
        print(f"[DEBUG] reranked count: {len(reranked_docs)}")

        # 去重（按 note_id）
        seen = set()
        unique_docs = []
        for doc in reranked_docs:
            note_id = doc.metadata.get("note_id")
            if note_id and note_id not in seen:
                seen.add(note_id)
                unique_docs.append(doc)

        if not unique_docs:
            return "您的笔记中暂无相关内容。"

        # 格式化返回给 LLM / Agent
        parts = []
        for i, doc in enumerate(unique_docs, 1):
            content = doc.page_content[:480].rstrip() + "..." if len(doc.page_content) > 480 else doc.page_content
            parts.append(
                f"【笔记 {i}】 标题：{doc.metadata.get('title', '无标题')}\n"
                f"内容：{content}"
            )

        return "\n\n".join(parts)

    return search_notes_rag