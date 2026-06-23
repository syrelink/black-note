"""
app/storage/sync.py

增量向量同步（MongoDB → Qdrant）。

全局单例：
  - BGEEmbeddings   — dense 向量（bge-m3，约 60MB，只加载一次）
  - FastEmbedSparse — sparse 向量（Qdrant/bm25，fastembed）
  - QdrantVectorStore（RetrievalMode.HYBRID，供 RAG 检索复用）
  - AsyncQdrantClient（供 Celery worker 写入 Qdrant）
"""

import uuid
import logging
from uuid import UUID

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.models import (
    Distance,
    Filter,
    FieldCondition,
    MatchValue,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode

from app.config import settings
from app.storage.embeddings import BGEEmbeddings
from app.storage.text_cleaner import preprocess_and_chunk

logger = logging.getLogger(__name__)

_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

_embeddings:        BGEEmbeddings | None     = None
_sparse_embeddings: FastEmbedSparse | None   = None
_sync_qdrant:       QdrantClient | None      = None
_async_qdrant:      AsyncQdrantClient | None = None
_vectorstore:       QdrantVectorStore | None = None


def get_embeddings() -> BGEEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = BGEEmbeddings()
    return _embeddings


def get_sparse_embeddings() -> FastEmbedSparse:
    global _sparse_embeddings
    if _sparse_embeddings is None:
        _sparse_embeddings = FastEmbedSparse(model_name="Qdrant/bm25")
    return _sparse_embeddings


def get_sync_qdrant_client() -> QdrantClient:
    global _sync_qdrant
    if _sync_qdrant is None:
        _sync_qdrant = QdrantClient(url=settings.QDRANT_URL)
        _ensure_collection(_sync_qdrant)
    return _sync_qdrant


def _get_async_qdrant_client() -> AsyncQdrantClient:
    global _async_qdrant
    if _async_qdrant is None:
        _async_qdrant = AsyncQdrantClient(url=settings.QDRANT_URL)
    return _async_qdrant


def _ensure_collection(client: QdrantClient) -> None:
    """创建集合（若不存在）：同时配置 dense 和 sparse 向量。"""
    existing = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION not in existing:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config={
                "": VectorParams(size=settings.QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "text-sparse": SparseVectorParams(),
            },
        )
        logger.info("Qdrant 集合已创建（dense + sparse）: %s", settings.QDRANT_COLLECTION)


def get_vectorstore() -> QdrantVectorStore:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = QdrantVectorStore(
            client=get_sync_qdrant_client(),
            collection_name=settings.QDRANT_COLLECTION,
            embedding=get_embeddings(),
            sparse_embedding=get_sparse_embeddings(),
            retrieval_mode=RetrievalMode.HYBRID,
            vector_name="",
            sparse_vector_name="text-sparse",
        )
    return _vectorstore


# ── Celery worker 使用的 async 同步函数 ──────────────────────────

async def sync_single_note(note_id: str) -> bool:
    """新建或更新笔记：从 MongoDB 读取，计算 dense + sparse 向量后写入 Qdrant。"""
    from bson import ObjectId
    from app.database import get_motor_client

    db   = get_motor_client()[settings.MONGODB_DB]
    note = await db.notes.find_one({"_id": ObjectId(note_id), "is_deleted": False})
    if not note:
        logger.info("笔记 %s 不存在或已删除，跳过同步", note_id)
        return False

    user        = await db.users.find_one({"_id": note["user_id"]})
    raw_content = f"{note['title']}\n{note.get('content', '') or ''}"
    metadata    = {
        "note_id":    note_id,
        "title":      note.get("title") or "",
        "user_id":    str(note["user_id"]),
        "author":     ((user.get("nickname") or user.get("username")) if user else "") or "",
        "like_count": note.get("like_count", 0),
        "created_at": str(note.get("created_at", "")),
    }

    chunks = preprocess_and_chunk(raw_content, metadata)
    if not chunks:
        logger.info("笔记 %s 无有效 chunk，跳过同步", note_id)
        return False

    qdrant = _get_async_qdrant_client()

    # 先删除旧 chunks（幂等）
    await qdrant.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="note_id", match=MatchValue(value=note_id))]
        ),
    )

    # 计算 dense 向量
    texts         = [c.page_content for c in chunks]
    dense_vectors = get_embeddings().embed_documents(texts)

    # 计算 sparse 向量（BM25 via fastembed）
    sparse_results = get_sparse_embeddings().embed_documents(texts)

    points = [
        PointStruct(
            id=str(uuid.uuid5(_NS, f"{note_id}:{i}")),
            vector={
                "": dense_vectors[i],
                "text-sparse": SparseVector(
                    indices=sparse_results[i].indices,
                    values=sparse_results[i].values,
                ),
            },
            payload={"page_content": texts[i], **chunks[i].metadata},
        )
        for i in range(len(chunks))
    ]
    await qdrant.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)

    logger.info("笔记 %s 向量同步完成（%d 个 chunk，dense + sparse）", note_id, len(chunks))
    return True


async def delete_note_from_vectorstore(note_id: str) -> bool:
    """从 Qdrant 删除笔记的所有 chunk。"""
    qdrant = _get_async_qdrant_client()
    await qdrant.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="note_id", match=MatchValue(value=note_id))]
        ),
    )
    logger.info("笔记 %s 已从 Qdrant 删除", note_id)
    return True
