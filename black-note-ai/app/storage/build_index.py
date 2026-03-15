"""
【RAG 标准流程】入库流程：
Step 1. Load   - 从 MySQL 读取原始笔记数据
Step 2. Split  - MarkdownHeader + Recursive 两阶段分块 + 清理
Step 3. Embed  - 用 BGEEmbeddings 生成向量
Step 4. Store  - 存入 ChromaDB（支持 hybrid）

一次性全量建库脚本，服务首次部署或数据重置时需要运行
"""

import os
import pymysql
from langchain_chroma import Chroma
from app.storage.embeddings import BGEEmbeddings

# ←←← 统一调用清理 + 分块模块
from app.storage.text_cleaner import preprocess_and_chunk

# ── Step 1: Load 加载数据──────────────────────────────────────────────────────────────
def load_notes_from_mysql():
    """Step 1: Load - 从 MySQL 读取全部未删除笔记（含作者信息）。"""
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


# ── Step 2+3: 转换成文档对象(内容+元数据) + 分块 ──────────────────────────────────
def notes_to_documents(notes):
    """
    Step 2: Split - 调用独立清理 + 分块模块
    每个笔记先清理 → 结构化分块 → 长度控制 → 过滤垃圾 chunk
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
        }

        # 调用统一清理 + 分块入口（核心优化点）
        processed_chunks = preprocess_and_chunk(raw_content, metadata)
        docs.extend(processed_chunks)

    return docs


# ── Step 4+5: chunks向量化 + 存储到向量数据库 ───────────────────────────────────────────
def store_to_chroma(chunks, embeddings):
    """
    使用 Chroma.from_documents 一行完成：
    - 向量化（dense）
    - 创建 collection
    - 持久化存储
    """
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")

    # 官方最佳实践：一行完成初始化 + 添加文档
    vectorstore = Chroma.from_documents(
        documents=chunks,                    # 你的 cleaned chunks
        embedding=embeddings,                # BGEEmbeddings
        persist_directory=chroma_dir,        # 本地持久化
        collection_name=collection_name,     # 指定 collection 名
    )

    print(f"✅ Chroma 索引库建库完成：{len(chunks)} 个 chunk")


if __name__ == "__main__":
    # ── 建库前先清空旧数据（保证幂等性）────────────────────
    import chromadb
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")
    
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        client.delete_collection(collection_name)
        print(f"🗑️  旧索引已清空：{collection_name}")
    except Exception:
        print("📭 未找到旧索引，直接建库")

    # ── 正式建库 ──────────────────────────────────────────
    notes = load_notes_from_mysql()
    print(f"✅ Step 1: Load 完成 → 读取笔记：{len(notes)} 条")

    docs = notes_to_documents(notes)
    print(f"✅ Step 2: Split + 清理完成 → 有效 chunk：{len(docs)} 个")

    embeddings = BGEEmbeddings()
    store_to_chroma(docs, embeddings)
    print(f"✅ 全量建库完成：{len(notes)} 条笔记 → {len(docs)} 个有效 chunk")