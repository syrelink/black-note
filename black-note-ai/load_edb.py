import os
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
import pymysql
import chromadb
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer
from typing import List

load_dotenv()

# ── BGE本地Embedding ──────────────────────────────
class BGEEmbeddings(Embeddings):
    def __init__(self):
        print("⏳ 加载 bge-m3 模型...")
        self.model = SentenceTransformer("BAAI/bge-m3", device="cpu")
        print("✅ 模型加载成功")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        batch_size = 4
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            print(f"  向量化进度: {min(i + batch_size, len(texts))}/{len(texts)}")
            all_embeddings.extend(
                self.model.encode(batch, normalize_embeddings=True,
                                  show_progress_bar=False).tolist()
            )
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()


# ── 从MySQL读取笔记 ───────────────────────────────
def load_notes_from_mysql():
    print("\n从MySQL读取笔记...")
    conn = pymysql.connect(
        host="127.0.0.1", port=3306,
        user="root", password="123456",
        database="black_note", charset="utf8mb4"
    )
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT
                    n.id, n.title, n.content, n.user_id,
                    n.like_count, n.created_at,
                    u.nickname, u.username
                FROM note n
                LEFT JOIN user u ON n.user_id = u.id
                WHERE n.is_deleted = 0
                ORDER BY n.created_at DESC
            """)
            notes = cursor.fetchall()
            print(f"✅ 读取到 {len(notes)} 条笔记")
            return notes
    finally:
        conn.close()


# ── 转成Document格式 ──────────────────────────────
def notes_to_documents(notes):
    print("\n转换为Document格式...")
    docs = []
    for note in notes:
        content = f"{note['title']}\n{note['content']}"
        docs.append(Document(
            page_content=content,
            metadata={
                "note_id":    str(note["id"]),
                "title":      note["title"] or "",
                "user_id":    str(note["user_id"]),
                "author":     note["nickname"] or note["username"] or "",
                "like_count": note["like_count"] or 0,
                "created_at": str(note["created_at"]),
            }
        ))
    print(f"✅ 转换完成，共 {len(docs)} 条")
    return docs


# ── 存入ChromaDB ──────────────────────────────────
def store_to_chroma(docs, embeddings):
    print("\n批量向量化并存入ChromaDB...")

    client = chromadb.PersistentClient(path="./chroma_db")

    # 确认删除旧数据
    existing = [c.name for c in client.list_collections()]
    if "black_note_all" in existing:
        client.delete_collection("black_note_all")
        print("已清空旧数据")
    else:
        print("无旧数据，直接创建")

    vectorstore = Chroma.from_documents(
        documents=docs,
        embedding=embeddings,
        persist_directory="./chroma_db",
        collection_name="black_note_all"
    )
    print(f"✅ 存储完成，共 {len(docs)} 条笔记已向量化")
    return vectorstore


# ── 语义搜索测试 ──────────────────────────────────
def test_search(vectorstore):
    print("\n【测试语义搜索...")
    queries = ["心情不好", "技术学习", "美食推荐", "旅行"]

    for query in queries:
        results = vectorstore.similarity_search_with_score(query, k=3)
        print(f"\n搜索「{query}」原始分数：")
        for doc, score in results:
            print(f"   score:{score:.4f} similarity:{1-score:.4f} [{doc.metadata['title']}]")


# ── 主入口 ────────────────────────────────────────
if __name__ == "__main__":
    notes       = load_notes_from_mysql()
    docs        = notes_to_documents(notes)
    embeddings  = BGEEmbeddings()
    vectorstore = store_to_chroma(docs, embeddings)
    test_search(vectorstore)