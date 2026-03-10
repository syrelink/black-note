import os
import pymysql
import chromadb
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from sentence_transformers import SentenceTransformer
from typing import List

load_dotenv()

# ── BGE本地Embedding（和Day2一样）─────────────────
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
                batch, normalize_embeddings=True, show_progress_bar=False
            ).tolist()
            all_embeddings.extend(embeddings)
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()


# ── 加载已有ChromaDB（不重新向量化）──────────────
def load_vectorstore(embeddings):
    print("📂 加载已有ChromaDB...")
    vectorstore = Chroma(
        persist_directory="./chroma_db",
        embedding_function=embeddings,
        collection_name="black_note_all"
    )
    count = vectorstore._collection.count()
    print(f"✅ 已加载，共 {count} 条笔记")
    return vectorstore


# ── 构建RAG Chain ─────────────────────────────────
def build_rag_chain(vectorstore):
    # 1. 检索器：召回最相关的3条笔记
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": 3,
            "filter": {"user_id": "3"}  # 只检索user_id=1的笔记
        }
    )

    # 2. LLM
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3  # 低温度，回答更稳定准确
    )

    # 3. Prompt模板
    # 关键设计：明确告诉大模型只能基于提供的笔记内容回答
    # 这是控制幻觉的核心手段
    prompt = ChatPromptTemplate.from_template("""
你是用户的私人笔记助手牧濑红莉栖。请严格基于以下笔记内容回答问题。

规则：
1. 只能使用下方提供的笔记内容作为依据
2. 如果笔记中没有相关内容，直接说"您的笔记中暂无相关内容"
3. 回答时注明来自哪篇笔记
4. 语言简洁自然，请带有助手牧濑红莉栖的性格语气，你就是牧濑红莉栖(命运石之门)

相关笔记内容：
{context}

用户问题：{question}

回答：""")

    # 4. 格式化召回的笔记
    def format_docs(docs):
        formatted = []
        for i, doc in enumerate(docs, 1):
            formatted.append(
                f"【笔记{i}】标题：{doc.metadata['title']}\n"
                f"作者：{doc.metadata['author']}\n"
                f"内容：{doc.page_content}\n"
            )
        return "\n".join(formatted)

    # 5. 组装Chain
    # RunnablePassthrough 把question原样传递
    # retriever 召回相关笔记
    # format_docs 格式化成字符串塞进prompt
    rag_chain = (
        {
            "context":  retriever | format_docs,
            "question": RunnablePassthrough()
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    return rag_chain


# ── 测试问答 ──────────────────────────────────────
def test_qa(rag_chain):
    print("\n" + "="*40)
    print("开始RAG问答测试")
    print("="*40)

    questions = [
        "我写过哪些关于技术学习的笔记？帮我总结一下",
        "有没有关于心情或情绪的笔记？",
        "我写过关于Redis的内容吗？",
        "有关于美食的笔记吗？",
    ]

    for q in questions:
        print(f"\n❓ 问题：{q}")
        print("-" * 30)
        answer = rag_chain.invoke(q)
        print(f"💬 回答：{answer}")
        print()


# ── 主入口 ────────────────────────────────────────
if __name__ == "__main__":
    embeddings  = BGEEmbeddings()
    vectorstore = load_vectorstore(embeddings)
    rag_chain   = build_rag_chain(vectorstore)
    test_qa(rag_chain)