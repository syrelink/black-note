"""
app/core/rag.py

RAG 混合检索：Qdrant native hybrid（dense + sparse）+ FlashRank 重排序。
BM25 稀疏向量在写入时由 fastembed 计算并存入 Qdrant，
检索时通过 RetrievalMode.HYBRID 一次查询同时走 dense + sparse，
用 user_id payload filter 隔离用户数据。
"""

from typing import List

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.models import Filter, FieldCondition, MatchValue
from flashrank import Ranker, RerankRequest


def make_rag_retriever(vectorstore: QdrantVectorStore, user_id: str = None):
    """
    构建 per-user 混合检索器。
    vectorstore 已在 sync.py 中配置为 RetrievalMode.HYBRID，
    这里只需附加 user_id 过滤条件即可，无需在内存中建 BM25 索引。
    """
    user_filter = Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
    )
    return vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 20, "filter": user_filter},
    )


def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """FlashRank 重排序（CPU 密集，由调用方用 asyncio.to_thread 包裹）。"""
    if not docs:
        return []

    valid_docs = [doc for doc in docs if len(doc.page_content.strip()) >= 10]
    passages   = [doc.page_content.strip() for doc in valid_docs]

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
