"""
【RAG 标准流程】入库流程
"""

import os
import pymysql
from langchain_chroma import Chroma
from app.storage.embeddings import BGEEmbeddings
from app.storage.text_cleaner import preprocess_and_chunk

# ── Step 1: Load 加载数据 ──────────────────────────────────────────────
def load_notes_from_mysql():
    """Step 1: Load - 从 MySQL 读取全部未删除笔记"""
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
                       n.like_count, n.created_at, n.is_deleted, 
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


# ── Step 2+3: 转换成文档对象 + 分块 ─────────────────────────────────────
def notes_to_documents(notes):
    """
    Step 2: Split 
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
            "is_deleted": int(note.get("is_deleted")), 
        }

        # 调用统一清理 + 分块
        processed_chunks = preprocess_and_chunk(raw_content, metadata)
        docs.extend(processed_chunks)

    return docs


# ── Step 4+5: 向量化 + 存储（保持不变） ─────────────────────────────────────
def store_to_chroma(chunks, embeddings):
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")

    # 清空旧库（保证新 metadata 生效）
    import chromadb
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        client.delete_collection(collection_name)
        print(f"🗑️  旧索引已清空（metadata 将重新生成）")
    except Exception:
        pass

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=chroma_dir,
        collection_name=collection_name,
    )

    print(f"✅ Chroma 索引库建库完成：{len(chunks)} 个 chunk")


if __name__ == "__main__":
    notes = load_notes_from_mysql()
    print(f"✅ Step 1: Load 完成 → 读取笔记：{len(notes)} 条")

    docs = notes_to_documents(notes)
    print(f"✅ Step 2: Split + 清理完成 → 有效 chunk：{len(docs)} 个")

    embeddings = BGEEmbeddings()
    store_to_chroma(docs, embeddings)
    print(f"✅ 全量建库完成！现在 is_deleted 已正确写入 metadata")