"""
app/core/rag.py
负责 RAG 检索逻辑。

改动说明：
  - make_rag_retriever：返回检索器本身（不再返回 @tool 函数）
    用户过滤改到 tools.py 里统一处理
  - rerank_docs：不变
  - 移除原来的 make_rag_tool，该职责已移入 tools.py 的 search_notes 工具
"""

import os
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from flashrank import Ranker, RerankRequest
import jieba

load_dotenv()

# app/core/rag.py

_retriever_cache: dict = {}   # key = collection_name，value = retriever

def make_rag_retriever(vectorstore: Chroma, user_id: str = None):
    """
    构建混合检索器，结果缓存在模块变量里。
    同一个 vectorstore 只建一次，后续直接复用。
    """
    cache_key = f"{vectorstore._collection.name}:{user_id}"

    if cache_key in _retriever_cache:
        return _retriever_cache[cache_key]

    # ── 第一次调用才真正构建 ──────────────────────────────
    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": 20,
            "filter": {
                "$and": [
                    {"user_id":    {"$eq": str(user_id)}},
                    {"is_deleted": {"$eq": 0}},
                ]
            }
        },
    )

    result = vectorstore.get(where={"user_id": str(user_id)})
    documents = [
        Document(page_content=text or "", metadata=meta or {})
        for text, meta in zip(
            result.get("documents", []),
            result.get("metadatas", []),
        )
        if (meta or {}).get("is_deleted", 0) == 0
    ]

    def chinese_preprocess(text: str):
        return list(jieba.cut(text))

    bm25_retriever = BM25Retriever.from_documents(
        documents,
        k=20,
        preprocess_func=chinese_preprocess,
    )

    retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.48, 0.52],
        c=60,
    )

    _retriever_cache[cache_key] = retriever   # 存入缓存
    print(f"✅ BM25 检索器已构建并缓存（{len(documents)} 个文档）")
    return retriever

def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """FlashRank 重排序（防御性实现，不变）"""
    if not docs:
        return []

    passages = [doc.page_content.strip() for doc in docs if len(doc.page_content.strip()) >= 10]
    valid_docs = [doc for doc in docs if len(doc.page_content.strip()) >= 10]

    if not passages:
        return docs[:top_n]

    try:
        ranker = Ranker(model_name="BAAI/bge-reranker-v2-m3")
        results = ranker.rerank(RerankRequest(query=query.strip(), passages=passages))

        sorted_indices = sorted(
            range(len(results)),
            key=lambda i: float(results[i].get("score", 0)),
            reverse=True,
        )
        return [valid_docs[i] for i in sorted_indices[:top_n] if i < len(valid_docs)]

    except Exception:
        return valid_docs[:top_n]

