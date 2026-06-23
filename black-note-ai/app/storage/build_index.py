"""
【RAG 标准流程】全量建库

从 MongoDB 读取全部未删除笔记，分块后计算 dense + sparse 向量写入 Qdrant。
每次运行会删除旧集合并重建（幂等）。

运行命令：
  cd black-note-ai
  python -m app.storage.build_index
"""

import asyncio
import uuid
from uuid import UUID

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import QdrantClient
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
from langchain_qdrant import FastEmbedSparse

from app.config import settings
from app.storage.embeddings import BGEEmbeddings
from app.storage.text_cleaner import preprocess_and_chunk

_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


async def load_notes_from_mongodb():
    """Step 1: Load — 从 MongoDB 读取全部未删除笔记（含作者信息）。"""
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db     = client[settings.MONGODB_DB]

    pipeline = [
        {"$match": {"is_deleted": False}},
        {"$sort":  {"created_at": -1}},
        {"$lookup": {
            "from":         "users",
            "localField":   "user_id",
            "foreignField": "_id",
            "as":           "author_docs",
        }},
        {"$addFields": {"author": {"$arrayElemAt": ["$author_docs", 0]}}},
        {"$project":   {"author_docs": 0}},
    ]

    notes = await db.notes.aggregate(pipeline).to_list(None)
    client.close()
    return notes


def notes_to_documents(notes):
    """Step 2+3: 转换 + 分块。"""
    docs = []
    for note in notes:
        author      = note.get("author") or {}
        raw_content = f"{note['title']}\n{note.get('content', '') or ''}"
        metadata    = {
            "note_id":    str(note["_id"]),
            "title":      note.get("title") or "",
            "user_id":    str(note["user_id"]),
            "author":     author.get("nickname") or author.get("username") or "",
            "like_count": note.get("like_count", 0),
            "created_at": str(note.get("created_at", "")),
        }
        docs.extend(preprocess_and_chunk(raw_content, metadata))
    return docs


def store_to_qdrant(chunks, dense_emb: BGEEmbeddings, sparse_emb: FastEmbedSparse) -> None:
    """Step 4+5: 计算 dense + sparse 向量并写入 Qdrant（全量重建）。"""
    client = QdrantClient(url=settings.QDRANT_URL)

    # 删除旧集合，全量重建
    existing = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION in existing:
        client.delete_collection(settings.QDRANT_COLLECTION)
        print("旧 Qdrant 集合已清空")

    client.create_collection(
        collection_name=settings.QDRANT_COLLECTION,
        vectors_config={
            "": VectorParams(size=settings.QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "text-sparse": SparseVectorParams(),
        },
    )
    print("Qdrant 集合已创建（dense + sparse）")

    batch_size = 64
    total      = len(chunks)

    for start in range(0, total, batch_size):
        batch  = chunks[start : start + batch_size]
        texts  = [c.page_content for c in batch]

        dense_vectors  = dense_emb.embed_documents(texts)
        sparse_results = sparse_emb.embed_documents(texts)

        points = [
            PointStruct(
                id=str(uuid.uuid5(_NS, f"{batch[i].metadata['note_id']}:{start + i}")),
                vector={
                    "": dense_vectors[i],
                    "text-sparse": SparseVector(
                        indices=sparse_results[i].indices,
                        values=sparse_results[i].values,
                    ),
                },
                payload={"page_content": texts[i], **batch[i].metadata},
            )
            for i in range(len(batch))
        ]
        client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
        print(f"  上传 {min(start + batch_size, total)}/{total} chunks")

    client.close()
    print(f"Qdrant 全量建库完成：{total} 个 chunk（dense + sparse）")


if __name__ == "__main__":
    notes = asyncio.run(load_notes_from_mongodb())
    print(f"Step 1 完成 → 读取笔记：{len(notes)} 条")

    chunks = notes_to_documents(notes)
    print(f"Step 2+3 完成 → 有效 chunk：{len(chunks)} 个")

    dense_emb  = BGEEmbeddings()
    sparse_emb = FastEmbedSparse(model_name="Qdrant/bm25")
    store_to_qdrant(chunks, dense_emb, sparse_emb)
