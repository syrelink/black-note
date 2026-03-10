from langchain_community.document_loaders import PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from embeddings import BGEEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore

file_path = "/Users/syr/Work-space/code-project/black-note/langchain_test/resum.pdf"
loader = PyMuPDFLoader(file_path)

docs = loader.load() # 返回 Document 列表，每页一个
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,        # 每个块最大 1000 字符
    chunk_overlap=200,      # 相邻块重叠 200 字符，保留上下文
    add_start_index=True  # 在 metadata 中记录原文档中的起始位置
)
all_splits = text_splitter.split_documents(docs)

embeddings = BGEEmbeddings()

vector_store = InMemoryVectorStore(embeddings)

# 添加分割的文档（自动嵌入）
ids = vector_store.add_documents(documents=all_splits)

# 相似度查询
res = vector_store.similarity_search(
    "有几个技术？",
    k=3
)

res_score = vector_store.similarity_search_with_score(
    "有几个技术？",
    k=3
)

for doc,score in res_score:
    print(f"Score: {score}, Content: {doc.page_content[:100]}...")  # 输出文档和相似度分数