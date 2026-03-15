"""
增量同步模块（app/storage/sync.py）
新笔记发布/编辑/删除时，同步更新 ChromaDB。

核心优化：
1. BGEEmbeddings 和 Chroma 实例改为模块级单例
   → 服务启动时只加载一次 bge-m3 模型，后续同步无需重载
2. sync_single_note / delete_note_from_vectorstore 复用全局实例
   → 发布笔记速度从"等几秒"变成"毫秒级"
3. main.py 里用 BackgroundTasks 异步执行同步
   → Spring Boot 调完接口立刻拿到响应，用户无感知
"""

import os
from typing import Optional

import chromadb
import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.storage.embeddings import BGEEmbeddings
from app.storage.text_cleaner import preprocess_and_chunk


# ── 配置（与全量建库保持一致）────────────────────────────────
CHROMA_DIR       = os.getenv("CHROMA_DIR",       "./chroma_db")
COLLECTION_NAME  = os.getenv("CHROMA_COLLECTION", "black_note_all")

DB_CONFIG = {
    "host":     os.getenv("MYSQL_HOST",     "127.0.0.1"),
    "port":     int(os.getenv("MYSQL_PORT", "3306")),
    "user":     os.getenv("MYSQL_USER",     "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "database": os.getenv("MYSQL_DB",       "black_note"),
    "charset":  "utf8mb4",
}


# ── 模块级单例：整个服务生命周期只初始化一次 ─────────────────
# bge-m3 模型约 60MB，每次重新加载要好几秒，缓存后复用即可
_embeddings:  BGEEmbeddings | None = None
_vectorstore: Chroma | None        = None


def get_embeddings() -> BGEEmbeddings:
    """获取全局 embeddings 单例，首次调用时加载模型"""
    global _embeddings
    if _embeddings is None:
        _embeddings = BGEEmbeddings()
    return _embeddings


def get_vectorstore() -> Chroma:
    """获取全局 vectorstore 单例，复用同一个 embeddings 实例"""
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=get_embeddings(),   # 复用，不重建
            collection_name=COLLECTION_NAME,
        )
    return _vectorstore


# ── 内部工具函数 ──────────────────────────────────────────────

def _fetch_note(note_id: int) -> Optional[dict]:
    """从 MySQL 查询单条未删除笔记（含作者信息）"""
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


# ── 核心同步函数 ──────────────────────────────────────────────

def sync_single_note(note_id: int) -> bool:
    """
    新增/更新笔记的完整同步流程：
    Load → 清理分块 → 删旧 → 写新 → 清 BM25 缓存

    由 main.py 的 BackgroundTasks 异步调用，不阻塞 HTTP 响应。
    """
    try:
        note = _fetch_note(note_id)
        if not note:
            print(f"笔记 {note_id} 不存在或已删除，跳过同步")
            return False

        raw_content = f"{note['title']}\n{note['content']}"
        metadata = {
            "note_id":    str(note["id"]),
            "title":      note["title"] or "",
            "user_id":    str(note["user_id"]),
            "author":     note["nickname"] or note["username"] or "",
            "like_count": note["like_count"] or 0,
            "created_at": str(note["created_at"]),
        }

        chunks = preprocess_and_chunk(raw_content, metadata)
        if not chunks:
            print(f"笔记 {note_id} 预处理后无有效 chunk，跳过同步")
            return False

        # 复用全局 vectorstore，不重新加载模型
        vs = get_vectorstore()

        # 先删旧 chunk（保证幂等性）
        client     = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(where={"note_id": str(note_id)})

        # 写入新 chunk
        vs.add_documents(chunks)

        # 清除 BM25 缓存，下次搜索时重建（含新笔记）
        from app.core.rag import _retriever_cache
        _retriever_cache.clear()

        print(f"✅ 笔记 {note_id} 增量同步成功（{len(chunks)} 个有效 chunk）")
        return True

    except Exception as e:
        print(f"❌ 笔记 {note_id} 同步失败：{str(e)}")
        return False


def delete_note_from_vectorstore(note_id: int) -> bool:
    """
    删除笔记：按 note_id 删除所有相关 chunk，并清除 BM25 缓存

    由 main.py 的 BackgroundTasks 异步调用，不阻塞 HTTP 响应。
    """
    try:
        client     = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(COLLECTION_NAME)
        result     = collection.delete(where={"note_id": str(note_id)})

        deleted_count = result.get("deleted", 0) if isinstance(result, dict) else 0

        if deleted_count > 0:
            print(f"✅ 笔记 {note_id} 已删除（移除 {deleted_count} 个 chunk）")
        else:
            print(f"⚠️  笔记 {note_id} 在向量库中无匹配 chunk")

        # 清除 BM25 缓存
        from app.core.rag import _retriever_cache
        _retriever_cache.clear()

        return True

    except Exception as e:
        print(f"❌ 删除笔记 {note_id} 失败：{str(e)}")
        return False