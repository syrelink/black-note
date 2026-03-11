import os
from typing import Optional

import chromadb
import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document

from .embeddings import BGEEmbeddings


CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "black_note_all")

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "database": os.getenv("MYSQL_DB", "black_note"),
    "charset": "utf8mb4",
}


def get_vectorstore() -> Chroma:
    """加载已有 ChromaDB（不全量重建）。"""
    embeddings = BGEEmbeddings()
    return Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def _fetch_note(note_id: int) -> Optional[dict]:
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT n.id, n.title, n.content, n.user_id,
                       n.like_count, n.created_at,
                       u.nickname, u.username
                FROM note n
                LEFT JOIN user u ON n.user_id = u.id
                WHERE n.id = %s AND n.is_deleted = 0
                """,
                (note_id,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


def sync_single_note(note_id: int) -> bool:
    """增量同步单条笔记到向量库（SpringBoot 发布后调用）。"""
    try:
        note = _fetch_note(note_id)
        if not note:
            return False

        doc = Document(
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
        vectorstore = get_vectorstore()
        vectorstore.add_documents([doc])
        print(f"✅ 笔记 {note_id} 已同步入库")
        return True
    except Exception as e:
        print(f"❌ 同步失败：{e}")
        return False


def delete_note_from_vectorstore(note_id: int) -> bool:
    """按 note_id 从 ChromaDB 移除（SpringBoot 删除后调用）。"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(where={"note_id": str(note_id)})
        print(f"✅ 笔记 {note_id} 已从向量库删除")
        return True
    except Exception as e:
        print(f"❌ 删除失败：{e}")
        return False

