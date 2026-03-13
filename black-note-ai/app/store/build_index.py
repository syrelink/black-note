"""
【RAG 标准流程】入库流程：
Step 1. Load   - 从 MySQL 读取原始笔记数据
Step 2. Split  - MarkdownHeader + Recursive 两阶段分块 + 清理
Step 3. Embed  - 用 BGEEmbeddings 生成向量
Step 4. Store  - 存入 ChromaDB（支持 hybrid）

一次性全量建库脚本，服务首次部署或数据重置时需要运行
"""

import os
import chromadb
import pymysql
from typing import List
from langchain_chroma import Chroma
from chromadb.utils.embedding_functions import ChromaBm25EmbeddingFunction
from langchain_core.documents import Document
from app.store.embeddings import BGEEmbeddings

# ←←← 统一调用清理 + 分块模块
from app.store.text_cleaner import preprocess_and_chunk


# ── Step 1: Load ──────────────────────────────────────────────────────────────
def load_notes_from_mysql():
    """Step 1: Load - 从 MySQL 读取全部未删除笔记（含作者信息）。"""
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "123456"),
        database=os.getenv("MYSQL_DB", "black_note"),
        charset="utf8mb4",
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT n.id, n.title, n.content, n.user_id,
                       n.like_count, n.created_at,
                       u.nickname, u.username
                FROM note n
                LEFT JOIN user u ON n.user_id = u.id
                WHERE n.is_deleted = 0
                ORDER BY n.created_at DESC
                """
            )
            return cursor.fetchall()
    finally:
        conn.close()


# ── Step 1 → Step 2 准备：转成 Document 对象 ──────────────────────────────────
def notes_to_documents(notes):
    """
    Step 2: Split - 调用独立清理 + 分块模块
    每个笔记先清理 → 结构化分块 → 长度控制 → 过滤垃圾 chunk
    """
    docs = []
    for note in notes:
        raw_content = f"{note['title']}\n{note['content']}"
        metadata = {
            "note_id": str(note["id"]),
            "title": note["title"] or "",
            "user_id": str(note["user_id"]),
            "author": note["nickname"] or note["username"] or "",
            "like_count": note["like_count"] or 0,
            "created_at": str(note["created_at"]),
        }

        # 调用统一清理 + 分块入口（核心优化点）
        processed_chunks = preprocess_and_chunk(raw_content, metadata)
        docs.extend(processed_chunks)

    return docs


# ── Step 3 + Step 4: Embed + Store ───────────────────────────────────────────
def store_to_chroma(chunks, embeddings):
    """
    Step 3: Embed + Step 4: Store
    生成 dense 向量 + BM25 sparse 向量，一次性存入 Chroma（支持 hybrid）
    """
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")

    client = chromadb.PersistentClient(path=chroma_dir)

    # 清空旧 collection
    existing = [c.name for c in client.list_collections()]
    if collection_name in existing:
        client.delete_collection(collection_name)

    bm25_ef = ChromaBm25EmbeddingFunction(k=1.2, b=0.75, avg_doc_length=256.0)

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

    ids = [str(i) for i in range(len(chunks))]
    texts = [doc.page_content for doc in chunks]
    metadatas = [doc.metadata for doc in chunks]

    dense_embeddings = embeddings.embed_documents(texts)

    collection.add(
        ids=ids,
        documents=texts,
        embeddings=dense_embeddings,
        metadatas=metadatas
    )

    print(f"✅ Chroma hybrid-ready collection 建库完成：{len(chunks)} 个 chunk")


if __name__ == "__main__":
    notes = load_notes_from_mysql()
    print(f"📄 Step 1: Load 完成 → 读取笔记：{len(notes)} 条")

    docs = notes_to_documents(notes)
    print(f"✅ Step 2: Split + 清理完成 → 有效 chunk：{len(docs)} 个")

    embeddings = BGEEmbeddings()
    store_to_chroma(docs, embeddings)
    print(f"✅ 全量建库完成：{len(notes)} 条笔记 → {len(docs)} 个有效 chunk")