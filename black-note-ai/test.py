import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer
from langchain_core.prompts import ChatPromptTemplate
from typing import List
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# ── BGE本地Embedding（和之前一样）─────────────────
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
            embeddings = self.model.encode(
                batch, normalize_embeddings=True,
                show_progress_bar=False
            ).tolist()
            all_embeddings.extend(embeddings)
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(
            text, normalize_embeddings=True
        ).tolist()


# ── 加载ChromaDB ──────────────────────────────────
def load_vectorstore(embeddings):
    print("📂 加载ChromaDB...")
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings,
        collection_name="black_note_all"
    )
    print(f"✅ 已加载，共 {vectorstore._collection.count()} 条笔记")
    return vectorstore

def print_retrieved_docs_with_score(question, vectorstore, k=3):
    # 使用 similarity_search_with_score 获取文档 + 分数
    results = vectorstore.similarity_search_with_score(question, k=k)
    
    print(f"\n【检索到的 Top {k} 篇笔记（带相似度分数，越高越相关）】")
    for i, (doc, score) in enumerate(results, 1):
        print(f"【笔记 {i}】 相似度: {score:.4f}")
        print(doc.page_content.strip())
        print("-" * 50)
    print()


def build_chain(vectorstore):

    # 检索器，返回documents对象列表
    retriever = vectorstore.as_retriever(
        search_kwargs = {"k":3}
    )

    # 大模型
    llm = ChatOpenAI(
        api_key = os.getenv("DEEPSEEK_API_KEY"),
        base_url = os.getenv("DEEPSEEK_BASE_URL"),
        model = os.getenv("DEEPSEEK_MODEL"),
        temperature = 0.3,
        streaming=True,
    )

    # prompt提示词
    prompt = ChatPromptTemplate.from_messages([
        ("system","你是我的助手名叫牧濑红莉栖（命运石之门的角色）。请你扮演她，回答用户的问题"),
        ("human","以下是相关笔记内容：{context}\n用户问题：{question}\n请直接给出回答：")

    ])   

    # 格式化函数，把检索到的笔记变成字符串
    def format_docs(docs):
        if not docs:
            return "（没有找到任何相关笔记）"
        formatted = []
        for i, doc in enumerate(docs, 1):
            formatted.append(f"【日记 {i}】\n{doc.page_content.strip()}")
        return "\n\n".join(formatted)

    # 组装Chain
    chain = (
        {
            "context": retriever | format_docs,
            "question": RunnablePassthrough()
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    return chain

if __name__ == "__main__":
    embeddings = BGEEmbeddings()
    vectorstore = load_vectorstore(embeddings)
    reg_chain = build_chain(vectorstore)
    question = "牧濑红莉栖你想出去玩吗？还是说想听我讲故事？"
    print_retrieved_docs_with_score(question, vectorstore)

    print("\n===== 开始 =====\n")
    print(question)
    for chunk in reg_chain.stream(question):
        print(chunk, end="", flush=True)

    print("\n\n===== 结束 =====")