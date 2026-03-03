import pymysql
from langchain_chroma import Chroma
from langchain_core.documents import Document
from embeddings import BGEEmbeddings
import chromadb

CHROMA_DIR       = "./chroma_db"
COLLECTION_NAME  = "black_note_all"

DB_CONFIG = {
    "host":     "127.0.0.1",
    "port":     3306,
    "user":     "root",
    "password": "123456",
    "database": "black_note",
    "charset":  "utf8mb4",
}


def get_vectorstore() -> Chroma:
    """加载已有ChromaDB，不重新向量化"""
    embeddings = BGEEmbeddings()
    return Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def sync_single_note(note_id: int) -> bool:
    """
    新笔记发布后增量入库，Spring Boot调用此函数
    只向量化这一条，不影响其他数据
    """
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT n.id, n.title, n.content, n.user_id,
                       n.like_count, n.created_at,
                       u.nickname, u.username
                FROM note n
                LEFT JOIN user u ON n.user_id = u.id
                WHERE n.id = %s AND n.is_deleted = 0
            """, (note_id,))
            note = cursor.fetchone()
        conn.close()

        if not note:
            return False

        doc = Document(
            page_content=f"{note['title']}\n{note['content']}",
            metadata={
                "note_id":    str(note["id"]),
                "title":      note["title"] or "",
                "user_id":    str(note["user_id"]),
                "author":     note["nickname"] or note["username"] or "",
                "like_count": note["like_count"] or 0,
                "created_at": str(note["created_at"]),
            }
        )

        vectorstore = get_vectorstore()
        vectorstore.add_documents([doc])
        print(f"✅ 笔记 {note_id} 已同步入库")
        return True

    except Exception as e:
        print(f"❌ 同步失败：{e}")
        return False


def delete_note_from_vectorstore(note_id: int) -> bool:
    """笔记删除时同步从ChromaDB移除"""
    try:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(where={"note_id": str(note_id)})
        print(f"✅ 笔记 {note_id} 已从向量库删除")
        return True
    except Exception as e:
        print(f"❌ 删除失败：{e}")
        return False