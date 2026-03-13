# inspect_chunks.py
import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from app.store.embeddings import BGEEmbeddings  # 你的 embedding 类

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "black_note_all")

def inspect_all_chunks():
    vectorstore = Chroma(
        persist_directory=CHROMA_DIR,
        embedding_function=BGEEmbeddings(),
        collection_name=COLLECTION_NAME,
    )

    # 获取 collection 中的所有文档（注意：如果数据量很大，会很慢）
    collection = vectorstore._collection
    count = collection.count()
    print(f"总 chunk 数量: {count}\n")

    if count == 0:
        print("向量库中没有数据")
        return

    # 分批获取（避免一次性加载太多）
    batch_size = 50
    for offset in range(0, count, batch_size):
        result = collection.get(
            offset=offset,
            limit=batch_size,
            include=["documents", "metadatas"]
        )

        docs = result["documents"]
        metas = result["metadatas"]

        for i, (content, meta) in enumerate(zip(docs, metas)):
            note_id = meta.get("note_id", "未知")
            title = meta.get("title", "无标题")
            user_id = meta.get("user_id", "未知")
            
            # 先处理预览，再 f-string
            preview = content[:200].replace('\n', '\\n').replace('\r', '\\r')
            
            print(f"Chunk {offset + i + 1}")
            print(f"  note_id: {note_id}")
            print(f"  title:   {title}")
            print(f"  user_id: {user_id}")
            print(f"  内容预览: {preview}")
            print(f"  完整长度: {len(content)} 字符")
            print("-" * 60)

if __name__ == "__main__":
    inspect_all_chunks()