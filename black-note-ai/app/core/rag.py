"""
app/core/rag.py

RAG 混合检索（Qdrant 向量 + BM25），结果缓存在模块变量里。
"""

from typing import List

import jieba
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Filter, FieldCondition, MatchValue
from flashrank import Ranker, RerankRequest

from app.config import settings

_retriever_cache: dict = {}   # key = "qdrant:{user_id}"


def make_rag_retriever(vectorstore: QdrantVectorStore, user_id: str = None):
    """
    构建混合检索器，结果缓存在模块变量里。
    同一用户只建一次，后续复用；笔记更新后 sync.py 会清空缓存。
    """
    cache_key = f"qdrant:{user_id}"
    if cache_key in _retriever_cache:
        return _retriever_cache[cache_key]

    user_filter = Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
    )

    # Qdrant vector retriever with per-user filter
    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 20, "filter": user_filter},
    )

    # Scroll all user docs from Qdrant for BM25
    qdrant_client = vectorstore.client
    all_points = []
    offset = None
    while True:
        points, next_offset = qdrant_client.scroll(
            collection_name=settings.QDRANT_COLLECTION,
            scroll_filter=user_filter,
            with_payload=True,
            limit=1000,
            offset=offset,
        )
        all_points.extend(points)
        if next_offset is None:
            break
        offset = next_offset

    documents = [
        Document(
            page_content=p.payload.get("page_content", ""),
            metadata={k: v for k, v in p.payload.items() if k != "page_content"},
        )
        for p in all_points
    ]

    def chinese_preprocess(text: str):
        return list(jieba.cut(text))

    bm25_retriever = BM25Retriever.from_documents(
        documents, k=20, preprocess_func=chinese_preprocess
    )

    retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.48, 0.52],
        c=60,
    )

    _retriever_cache[cache_key] = retriever
    print(f"BM25 检索器已构建并缓存（{len(documents)} 个文档，user={user_id}）")
    return retriever


def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """FlashRank 重排序。"""
    if not docs:
        return []

    passages  = [doc.page_content.strip() for doc in docs if len(doc.page_content.strip()) >= 10]
    valid_docs = [doc for doc in docs if len(doc.page_content.strip()) >= 10]

    if not passages:
        return docs[:top_n]

    try:
        ranker  = Ranker(model_name="BAAI/bge-reranker-v2-m3")
        results = ranker.rerank(RerankRequest(query=query.strip(), passages=passages))
        sorted_indices = sorted(
            range(len(results)),
            key=lambda i: float(results[i].get("score", 0)),
            reverse=True,
        )
        return [valid_docs[i] for i in sorted_indices[:top_n] if i < len(valid_docs)]
    except Exception:
        return valid_docs[:top_n]
