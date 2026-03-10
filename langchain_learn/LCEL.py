import os
from dotenv import load_dotenv
from typing import Dict

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from sentence_transformers import SentenceTransformer
from langchain_core.embeddings import Embeddings

load_dotenv()


# ── 自定义 Embedding ───────────────────────────────────────────────
class BGEEmbeddings(Embeddings):
    def __init__(self):
        self.model = SentenceTransformer("BAAI/bge-m3", device="cpu")

    def embed_documents(self, texts):
        return self.model.encode(texts, normalize_embeddings=True, batch_size=4).tolist()

    def embed_query(self, text):
        return self.model.encode(text, normalize_embeddings=True).tolist()


# ── 核心链构建函数 ────────────────────────────────────────────────
def build_conversational_rag_chain(
    persist_dir="./chroma_db",
    collection_name="black_note_all",
    k=3,
    temperature=0.3,
):
    # Embedding & Vectorstore
    embeddings = BGEEmbeddings()
    vectorstore = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        collection_name=collection_name
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})

    # LLM
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=temperature,
        streaming=True,
    )

    # 1. 历史问题改写 Prompt
    contextualize_prompt = ChatPromptTemplate.from_messages([
        ("system", """根据聊天历史将当前问题改写成一个独立、完整的检索查询。
仅输出改写后的查询，不要回答问题。
若问题已足够独立，直接输出原问题。"""),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    # 2. 最终回答 Prompt
    answer_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是我的助手「牧濑红莉栖」（命运石之门）。
语气：聪明、毒舌、偶尔中二，喜欢用科学/理论解释。
直接回答，不要复述上下文，不要说“根据笔记”。"""),
        MessagesPlaceholder("chat_history"),
        ("human", """相关笔记：
{context}

当前问题：{input}""")
    ])

    # 格式化检索结果
    def format_docs(docs):
        if not docs:
            return "（无相关笔记）"
        return "\n\n".join(
            f"【笔记 {i}】\n{doc.page_content.strip()}"
            for i, doc in enumerate(docs, 1)
        )

    # 历史存储（内存版）
    store: Dict[str, InMemoryChatMessageHistory] = {}

    def get_session_history(session_id: str) -> BaseChatMessageHistory:
        if session_id not in store:
            store[session_id] = InMemoryChatMessageHistory()
        return store[session_id]

    # 纯 LCEL: 历史感知检索链（手动构建）
    history_aware_retriever = (
        contextualize_prompt
        | llm
        | StrOutputParser()
        | retriever
        | format_docs
    )

    # 主链
    rag_chain = (
        RunnablePassthrough.assign(
            context=history_aware_retriever
        )
        | answer_prompt
        | llm
        | StrOutputParser()
    )

    # 加上对话记忆
    conversational_chain = RunnableWithMessageHistory(
        rag_chain,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )

    return conversational_chain, get_session_history, store


# ── 快速测试 ───────────────────────────────────────────────────────
def quick_test():
    chain, get_history, store = build_conversational_rag_chain()

    session_id = "test_user_001"

    while True:
        q = input("\n你：").strip()
        if q.lower() in ["quit", "退出", "q"]:
            break
        if q.lower() == "clear":
            if session_id in store:
                store[session_id].clear()
            print("历史已清空")
            continue

        try:
            response = chain.invoke(
                {"input": q},
                config={"configurable": {"session_id": session_id}}
            )
            print(f"红莉栖：{response}")
        except Exception as e:
            print(f"错误：{e}")


if __name__ == "__main__":
    quick_test()