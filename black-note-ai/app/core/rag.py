"""
app/rag.py
专门负责 RAG 检索逻辑（build_retriever + rerank_docs）
不包含任何 @tool 定义
"""

import os
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from flashrank import Ranker, RerankRequest

load_dotenv()


def build_retriever(vectorstore: Chroma, user_id: str):
    """
    构建混合检索器（Hybrid Retriever）
    
    核心思想：同时使用两种互补的检索方式，再通过 RRF 算法融合结果。
    - Dense（向量检索）：擅长语义相似匹配
    - BM25（关键词检索）：擅长精确匹配标题、专有名词、代码等
    """
    
    # ==================== 第一部分：Dense 向量检索器 ====================
    # 使用 Chroma 内置的向量索引进行语义搜索
    # filter 确保只能检索当前用户的笔记（多用户隔离）
    vector_retriever = vectorstore.as_retriever(
        search_type="similarity",           # 使用余弦相似度
        search_kwargs={
            "k": 12,                        # 先多召回一些，给后面的重排序留空间
            "filter": {"user_id": user_id}  # 关键：用户隔离
        }
    )

    # ==================== 第二部分：BM25 关键词检索器 ====================
    # 从 Chroma 中取出当前用户的所有 chunk，实时构建 BM25 索引
    # 这是为了让 BM25 也能只检索当前用户的数据
    result = vectorstore.get(where={"user_id": user_id})
    raw_docs = result.get("documents", [])
    metadatas = result.get("metadatas", [])
    documents = [
        Document(page_content=text, metadata=meta)
        for text, meta in zip(raw_docs, metadatas)
    ]
    bm25_retriever = BM25Retriever.from_documents(documents, k=12)

    # ==================== 第三部分：Ensemble 融合 ====================
    # 使用 EnsembleRetriever 把两种检索结果融合
    # weights=[0.48, 0.52] 表示 BM25 权重稍高（笔记场景中精确匹配更重要）
    # c=60 是 RRF 算法的平滑参数
    return EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.48, 0.52],      # 可根据实际效果微调
        c=60                       # RRF 参数，通常 60 效果较好
    )


def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """FlashRank 重排序（防御性实现）"""
    if not docs:
        return []

    passages = [doc.page_content.strip() for doc in docs if len(doc.page_content.strip()) >= 10]
    valid_docs = [doc for doc in docs if len(doc.page_content.strip()) >= 10]

    if not passages:
        return docs[:top_n]

    try:
        ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
        results = ranker.rerank(RerankRequest(query=query.strip(), passages=passages))

        sorted_indices = sorted(
            range(len(results)), 
            key=lambda i: float(results[i].get("score", 0)), 
            reverse=True
        )
        return [valid_docs[i] for i in sorted_indices[:top_n] if i < len(valid_docs)]
    except Exception:
        return valid_docs[:top_n]


def make_rag_tool(vectorstore: Chroma, user_id: str):
    """
    返回 RAG Tool 函数（供 tools.py 调用）
    """
    retriever = build_retriever(vectorstore, user_id)

    def search_notes_rag(query: str) -> str:
        """高级语义搜索（混合检索 + 重排序）"""
        raw_docs = retriever.invoke(query)
        if not raw_docs:
            return "您的笔记中暂无相关内容。"

        reranked = rerank_docs(query, raw_docs, top_n=7)

        # 去重 + 格式化
        seen = set()
        unique_docs = []
        for doc in reranked:
            note_id = doc.metadata.get("note_id")
            if note_id and note_id not in seen:
                seen.add(note_id)
                unique_docs.append(doc)

        if not unique_docs:
            return "您的笔记中暂无相关内容。"

        parts = []
        for i, doc in enumerate(unique_docs, 1):
            content = doc.page_content[:480] + "..." if len(doc.page_content) > 480 else doc.page_content
            parts.append(f"【笔记 {i}】标题：{doc.metadata.get('title', '无标题')}\n内容：{content}")
        return "\n\n".join(parts)

    return search_notes_rag