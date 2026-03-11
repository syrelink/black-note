"""
【RAG 标准流程】入库流程：
Step 1. Load   - 从 MySQL 读取原始笔记数据
Step 2. Split  - 用 RecursiveCharacterTextSplitter 分块
Step 3. Embed  - 用 BGEEmbeddings 生成向量
Step 4. Store  - 存入 ChromaDB 向量库

一次性全量建库脚本，服务首次部署或数据重置时需要运行
"""

import os
import chromadb
import pymysql
from langchain_chroma import Chroma
from chromadb.utils.embedding_functions import ChromaBm25EmbeddingFunction
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from embeddings import BGEEmbeddings


# ── Step 1: Load ──────────────────────────────────────────────────────────────
def load_notes_from_mysql():
    """从 MySQL 读取全部未删除笔记（含作者信息）。"""
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
                SELECT
                    n.id, n.title, n.content, n.user_id,
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
    把 MySQL 原始数据转成 LangChain Document 对象。
    page_content = 标题 + 内容（后续分块的原始文本）
    metadata     = 笔记元信息（检索结果中用于展示）
    """
    docs = []
    for note in notes:
        docs.append(
            Document(
                page_content=f"{note['title']}\n{note['content']}",
                metadata={
                    "note_id": str(note["id"]),
                    "title": note["title"] or "",
                    "user_id": str(note["user_id"]),
                    "author": note["nickname"] or note["username"] or "",
                    "like_count": note["like_count"] or 0,
                    "created_at": str(note["created_at"]),
                },
            )
        )
    return docs


# ── Step 2: Split ─────────────────────────────────────────────────────────────
def split_documents(docs):
    """
    用 RecursiveCharacterTextSplitter 对文档分块。
    按 \\n\\n → \\n → 空格 递归切分，优先保留段落完整性。
    - chunk_size=500：每块最多500字符，适合笔记这类短文本
    - chunk_overlap=50：块间重叠50字符，防止语义在边界处被截断
    每个 chunk 继承原始 Document 的 metadata（note_id、user_id 等）
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len,
    )
    return splitter.split_documents(docs)


# ── Step 3 + Step 4: Embed + Store ───────────────────────────────────────────
def store_to_chroma(chunks, embeddings):
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")
    # 持久化本地磁盘
    client = chromadb.PersistentClient(path=chroma_dir)

    # 清空旧数据
    existing = [c.name for c in client.list_collections()]
    if collection_name in existing:
        client.delete_collection(collection_name)

    # 创建 BM25 稀疏向量（参数可调）
    bm25_ef = ChromaBm25EmbeddingFunction(
        k=1.2,                    # BM25 k 参数（默认 1.2）
        b=0.75,                   # BM25 b 参数（默认 0.75）
        avg_doc_length=256.0,     # 平均文档长度（可根据你的 chunk 大小估算）
        token_max_length=40       # 单个 token 最大长度
    )

    # 创建 collection（不指定 embedding_function，因为我们手动 add dense）
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}  # dense 距离度量
    )

    # 准备数据
    ids = [str(i) for i in range(len(chunks))]
    texts = [doc.page_content for doc in chunks]
    metadatas = [doc.metadata for doc in chunks]

    # 生成 dense embeddings（你的 BGE-m3）
    dense_embeddings = embeddings.embed_documents(texts)

    # 添加到 collection（dense + sparse 同时存）
    # sparse_embeddings 由 bm25_ef 自动计算并存储
    collection.add(
        ids=ids,
        documents=texts,   # ← ChromaBm25EmbeddingFunction 会用这个自动算 sparse
        embeddings=dense_embeddings,  # dense 向量
        metadatas=metadatas
    )

    print(f"✅ Chroma hybrid-ready collection 建库完成：{len(chunks)} chunks")


if __name__ == "__main__":
    # Step 1: Load
    notes = load_notes_from_mysql()
    docs = notes_to_documents(notes)
    print(f"📄 读取笔记：{len(docs)} 条")

    # Step 2: Split
    chunks = split_documents(docs)
    print(f"✂️  分块结果：{len(chunks)} 个 chunk")

    # Step 3 + 4: Embed + Store
    embeddings = BGEEmbeddings()
    store_to_chroma(chunks, embeddings)
    print(f"✅ 全量建库完成：{len(docs)} 条笔记 → {len(chunks)} 个 chunk")