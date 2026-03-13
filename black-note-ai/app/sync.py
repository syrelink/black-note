"""
增量同步模块（app/store/sync.py）
新笔记发布/编辑/删除时，同步更新 ChromaDB。

核心流程：
- 新增/更新笔记：Load → 清理 + 分块 → Embed → Store（支持 hybrid）
- 删除笔记：按 note_id 删除所有相关 chunk

注意：已统一使用 preprocess_and_chunk 进行清理 + 分块，与全量建库保持一致
"""

import os
from typing import Optional

import chromadb
import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.store.embeddings import BGEEmbeddings
from app.store.text_cleaner import preprocess_and_chunk


# 配置（与全量建库保持一致）
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
    """获取 Chroma 实例（用于增量操作）"""
    embeddings = BGEEmbeddings()
    return Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def _fetch_note(note_id: int) -> Optional[dict]:
    """Step 1: Load - 从 MySQL 查询单条未删除笔记（含作者信息）。"""
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
    except Exception as e:
        print(f"查询笔记 {note_id} 失败: {e}")
        return None
    finally:
        conn.close()


def sync_single_note(note_id: int) -> bool:
    """
    Step 1~4: 新增/更新笔记的完整同步流程
    使用 preprocess_and_chunk 统一处理清理 + 分块
    """
    try:
        note = _fetch_note(note_id)
        if not note:
            print(f"笔记 {note_id} 不存在或已删除，无法同步")
            return False

        raw_content = f"{note['title']}\n{note['content']}"
        metadata = {
            "note_id": str(note["id"]),
            "title": note["title"],
            "user_id": str(note["user_id"]),
            "author": note["nickname"] or note["username"],
            "like_count": note["like_count"] or 0,
            "created_at": str(note["created_at"]),
        }

        # 调用统一清理 + 分块模块（核心）
        chunks = preprocess_and_chunk(raw_content, metadata)

        if not chunks:
            print(f"笔记 {note_id} 预处理后无有效 chunk，跳过同步")
            return False

        vectorstore = get_vectorstore()

        # 先删除旧 chunk（保证幂等性）
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(where={"note_id": str(note_id)})

        # 存入新 chunk（dense + sparse 自动）
        vectorstore.add_documents(chunks)

        print(f"✅ 笔记 {note_id} 增量同步成功（{len(chunks)} 个有效 chunk）")
        return True

    except Exception as e:
        print(f"❌ 笔记 {note_id} 同步失败：{str(e)}")
        return False


def delete_note_from_vectorstore(note_id: int) -> bool:
    """
    删除笔记：按 note_id 删除所有相关 chunk
    （仅适配当前 ChromaDB 新版，返回 dict 类型）
    """
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(COLLECTION_NAME)

        result = collection.delete(where={"note_id": str(note_id)})

        # 只处理 dict 类型（当前版本）
        deleted_count = result.get("deleted", 0) if isinstance(result, dict) else 0

        if deleted_count > 0:
            print(f"✅ 笔记 {note_id} 已删除（移除 {deleted_count} 个 chunk）")
        else:
            print(f"⚠️ 笔记 {note_id} 在向量库中无匹配 chunk")

        return True

    except Exception as e:
        print(f"❌ 删除笔记 {note_id} 失败：{str(e)}")
        return False