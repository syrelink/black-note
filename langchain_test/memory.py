import os
from dotenv import load_dotenv
from typing import Dict

# 新版正确导入（2026 年标准写法）
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.history_aware_retriever import create_history_aware_retriever

from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory

from sentence_transformers import SentenceTransformer

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


# ── 【标准版】带 Memory 的 RAG Chain ─────────────
def build_rag_with_memory(vectorstore, user_id: str):
    print("🔧 构建标准带Memory RAG Chain...")

    # 1. 检索器（保留你的 user_id 过滤）
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 3, "filter": {"user_id": user_id}}
    )

    # 2. LLM
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3
    )

    # 3. 【关键】上下文重写 Prompt（让 follow-up 问题也召回正确笔记）
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", "根据聊天历史和当前问题，把当前问题改写成一个独立、完整的查询。"),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
    ])

    # 4. 创建 history-aware retriever（官方标准）
    history_aware_retriever = create_history_aware_retriever(
        llm=llm,
        retriever=retriever,
        prompt=contextualize_q_prompt
    )

    # 5. 最终问答 Prompt（你的笔记助手人格）
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是用户的私人笔记助手牧濑红莉栖。
        严格基于下方提供的笔记内容回答问题。
        规则：
        1. 只能使用提供的笔记内容
        2. 没有相关内容时，直接说“您的笔记中暂无相关内容”
        3. 回答时注明来自哪篇笔记
        4. 语言简洁自然，带有牧濑红莉栖(命运石之门)的气质与性格

        相关笔记内容：
        {context}"""),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
    ])

    # 6. 问答子链
    question_answer_chain = qa_prompt | llm

    # 7. 完整 RAG Chain（官方 create_retrieval_chain）
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

    # 8. 自动管理历史（支持多用户）
    store: Dict[str, InMemoryChatMessageHistory] = {}

    def get_session_history(session_id: str) -> BaseChatMessageHistory:
        if session_id not in store:
            store[session_id] = InMemoryChatMessageHistory()
        return store[session_id]

    # 9. 最终可对话的 Chain（带 Memory）
    conversational_rag_chain = RunnableWithMessageHistory(
        rag_chain,
        get_session_history,
        input_messages_key="input",          # 用户输入的 key
        history_messages_key="chat_history", # 历史在 prompt 里的 key
        output_messages_key="answer",        # 输出字段
    )

    print("✅ 标准带Memory RAG Chain 构建完成！")
    return conversational_rag_chain



# ── 测试（超级简洁）────────────────────────────
def test_standard_rag():
    embeddings = BGEEmbeddings()
    vectorstore = load_vectorstore(embeddings)

    rag_chain = build_rag_with_memory(vectorstore, user_id="3")

    print("\n" + "="*50)
    print("🎉 标准版多轮对话已启动！（支持 history-aware）")
    print("输入 'quit' 退出，'clear' 清空当前用户历史")
    print("="*50)

    session_id = "user_3"   # 可以改成动态的

    while True:
        q = input("\n👤 你：").strip()
        if q.lower() in ["quit", "退出"]: 
            break
        if q.lower() == "clear":
            rag_chain.invoke({"input": ""}, config={"configurable": {"session_id": session_id}})  # 实际清空用 store[session_id].clear()
            print("🗑️ 历史已清空")
            continue

        response = rag_chain.invoke(
            {"input": q},
            config={"configurable": {"session_id": session_id}}
        )
        print(f"🤖 AI：{response['answer']}")


if __name__ == "__main__":
    test_standard_rag()