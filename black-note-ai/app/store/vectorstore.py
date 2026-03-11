"""
增量同步模块：
新笔记发布/删除时，同步更新 ChromaDB，无需全量重建。
同样遵循 RAG 入库流程：Load → Split → Embed → Store
"""

import os
from typing import Optional

import chromadb
import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

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

# ── Step 2: Split（与 build_index.py 保持一致）────────────────────────────────
_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    length_function=len,
)


def get_vectorstore() -> Chroma:
    """Step 4: Store — 加载已有 ChromaDB，不全量重建。"""
    embeddings = BGEEmbeddings()
    return Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def _fetch_note(note_id: int) -> Optional[dict]:
    """Step 1: Load — 从 MySQL 查单条笔记。"""
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
    """
    增量同步单条笔记：Load → Split → Embed → Store
    RabbitMQ 消费者收到消息后调用。
    """
    try:
        # Step 1: Load
        note = _fetch_note(note_id)
        if not note:
            return False

        # Step 1 → Step 2 准备：转成 Document
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

        # Step 2: Split — 与全量建库保持一致的分块策略
        chunks = _splitter.split_documents([doc])

        # Step 3 + 4: Embed + Store
        vectorstore = get_vectorstore()
        vectorstore.add_documents(chunks)
        print(f"✅ 笔记 {note_id} 已同步入库（{len(chunks)} 个 chunk）")
        return True
    except Exception as e:
        print(f"❌ 同步失败：{e}")
        return False


def delete_note_from_vectorstore(note_id: int) -> bool:
    """从 ChromaDB 删除指定笔记的所有 chunk（按 note_id 过滤）。"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(where={"note_id": str(note_id)})
        print(f"✅ 笔记 {note_id} 已从向量库删除")
        return True
    except Exception as e:
        print(f"❌ 删除失败：{e}")
        return False