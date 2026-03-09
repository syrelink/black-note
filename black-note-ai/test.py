# 新建 test_filter.py
import chromadb
from embeddings import BGEEmbeddings
from langchain_chroma import Chroma

embeddings = BGEEmbeddings()
vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=embeddings,
    collection_name="black_note_all"
)

# 不加filter
r1 = vectorstore.similarity_search("笔记", k=3)
print("无filter:", [r.metadata['title'] for r in r1])

# 加filter
r2 = vectorstore.similarity_search("笔记", k=3, filter={"user_id": "6"})
print("有filter user_id=6:", [r.metadata['title'] for r in r2])