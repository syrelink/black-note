"""
一次性全量建库脚本：
- 从 MySQL 读取全部未删除笔记
- 向量化后写入 ChromaDB（会清空旧 collection）
"""

import os

import chromadb
import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.store.embeddings import BGEEmbeddings


def load_notes_from_mysql():
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


def notes_to_documents(notes):
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


def store_to_chroma(docs, embeddings):
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")

    client = chromadb.PersistentClient(path=chroma_dir)
    existing = [c.name for c in client.list_collections()]
    if collection_name in existing:
        client.delete_collection(collection_name)

    Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory=chroma_dir,
        collection_name=collection_name,
    )


if __name__ == "__main__":
    notes = load_notes_from_mysql()
    docs = notes_to_documents(notes)
    embeddings = BGEEmbeddings()
    store_to_chroma(docs, embeddings)
    print(f"✅ 全量建库完成：{len(docs)} 条笔记")

