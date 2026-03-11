"""
【RAG 标准流程】检索流程（Chroma 原生 Hybrid 版）：
Step 5. Retrieve - 使用 Chroma 原生 hybrid_search（dense + sparse + RRF 自动融合）
Step 6. Generate - 封装成 Tool，由 Agent 调用

当前架构（2026 小项目最优版）：
- Chroma 原生 hybrid_search（服务器端 dense BGE + BM25 sparse + RRF 融合）
- FlashRank reranker（第二阶段精排，精度再提升 15-30%）

注意：必须先重建 collection 支持 sparse vector！
"""

import os
from typing import List
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_chroma import Chroma

from flashrank import Ranker, RerankRequest

load_dotenv()


def build_retriever(vectorstore: Chroma, user_id: str):
    """
    返回 hybrid_retriever 函数（兼容 .invoke(query) 调用方式）
    使用 Chroma 原生 hybrid_search + RRF 融合
    """
    def hybrid_retriever(query: str, k: int = 15):
        # 动态导入（避免不必要的依赖）
        from chromadb import Search, Knn, Rrf

        # RRF 融合配置（dense KNN + sparse 自动）
        # sparse 部分由 collection 创建时注入的 DefaultSparseEmbeddingFunction 自动处理
        hybrid_rank = Rrf(
            ranks=[
                Knn(query=query, return_rank=True),   # dense 部分
                # sparse 部分由 Chroma 内部自动加入（无需手动写）
            ],
            k=60    # RRF 参数，越大融合越平滑
        )

        search_config = Search(
            query_texts=[query],
            where={"user_id": user_id},   # 关键：只查当前用户笔记
            n_results=k,
            rank=hybrid_rank
        )

        # 调用 Chroma 原生 hybrid_search
        docs = vectorstore.hybrid_search(search=search_config)
        return docs

    return hybrid_retriever


def rerank_docs(query: str, docs: List[Document], top_n: int = 6) -> List[Document]:
    """FlashRank 第二阶段精排（强烈推荐保留）"""
    if not docs:
        return []

    ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")  # 最轻量 ~33MB
    # 更强模型可选： "bge-reranker-v2-m3" 或 "rank-TKL"

    passages = [doc.page_content for doc in docs]
    rerank_request = RerankRequest(query=query, passages=passages)
    results = ranker.rerank(rerank_request)

    sorted_indices = sorted(
        range(len(results)),
        key=lambda i: results[i]["score"],
        reverse=True
    )
    return [docs[i] for i in sorted_indices[:top_n]]


def make_rag_tool(vectorstore: Chroma, user_id: str):
    """
    把检索器封装成 Tool，供 Agent 调用
    """
    retriever = build_retriever(vectorstore, user_id)

    @tool
    def search_notes_rag(query: str) -> str:
        """
        使用 Chroma 原生 hybrid search 检索用户笔记。
        已集成 dense + sparse + RRF + FlashRank rerank。
        """
        # Step 5: 原生 hybrid 召回（服务器端一次完成）
        raw_docs = retriever(query, k=18)   # 多召回一点给 rerank 用

        if not raw_docs:
            return "您的笔记中暂无相关内容。"

        # Step 5.5: FlashRank 精排（面试最能讲的亮点）
        reranked_docs = rerank_docs(query, raw_docs, top_n=7)

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

        # 格式化返回给 Agent
        formatted = []
        for i, doc in enumerate(unique_docs, 1):
            content = doc.page_content[:450] + "..." if len(doc.page_content) > 450 else doc.page_content
            formatted.append(
                f"【笔记 {i}】标题：{doc.metadata.get('title', '无标题')}\n"
                f"内容：{content}"
            )

        return "\n\n".join(formatted)

    return search_notes_rag