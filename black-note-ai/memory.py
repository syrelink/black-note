import os
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.messages import HumanMessage, AIMessage
from sentence_transformers import SentenceTransformer
from typing import List

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
        collection_name="black_note"
    )
    print(f"✅ 已加载，共 {vectorstore._collection.count()} 条笔记")
    return vectorstore


# ── 带Memory的RAG Chain ───────────────────────────
class RAGWithMemory:
    def __init__(self, vectorstore, user_id: str, max_history: int = 5):
        self.user_id    = user_id
        self.max_history = max_history
        # 对话历史，存HumanMessage和AIMessage对象
        self.history: List = []

        # 检索器，只查当前用户的笔记
        self.retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 3,
                "filter": {"user_id": user_id}
            }
        )

        # LLM
        self.llm = ChatOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL"),
            model=os.getenv("DEEPSEEK_MODEL"),
            temperature=0.3
        )

        # Prompt：加入chat_history占位符
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """你是用户的私人笔记助手。

规则：
1. 严格基于提供的笔记内容回答
2. 结合对话历史理解用户意图
3. 笔记中没有相关内容时，直接说"您的笔记中暂无相关内容"
4. 回答时注明来自哪篇笔记
5. 语言简洁自然

相关笔记内容：
{context}"""),
            # 对话历史插入这里
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

    def _format_docs(self, docs):
        formatted = []
        for i, doc in enumerate(docs, 1):
            formatted.append(
                f"【笔记{i}】标题：{doc.metadata['title']}\n"
                f"内容：{doc.page_content}\n"
            )
        return "\n".join(formatted)

    def _get_recent_history(self):
        # 只保留最近max_history轮，避免Token超限
        # 每轮=1条Human+1条AI，所以取 max_history*2 条消息
        return self.history[-(self.max_history * 2):]

    def chat(self, question: str) -> str:
        # 1. 检索相关笔记
        docs    = self.retriever.invoke(question)
        context = self._format_docs(docs)

        # 2. 构建输入，带上历史
        chain_input = {
            "context":      context,
            "chat_history": self._get_recent_history(),
            "question":     question,
        }

        # 3. 调用LLM
        chain    = self.prompt | self.llm | StrOutputParser()
        answer   = chain.invoke(chain_input)

        # 4. 把本轮对话存入历史
        self.history.append(HumanMessage(content=question))
        self.history.append(AIMessage(content=answer))

        return answer

    def clear_history(self):
        self.history = []
        print("🗑️  对话历史已清空")

    def show_history(self):
        print(f"\n📜 当前对话历史（{len(self.history)//2}轮）：")
        for i, msg in enumerate(self.history):
            role = "👤 用户" if isinstance(msg, HumanMessage) else "🤖 AI"
            print(f"  {role}：{msg.content[:50]}...")


# ── 测试多轮对话 ──────────────────────────────────
def test_multi_turn(rag: RAGWithMemory):
    print("\n" + "="*40)
    print("Day4 测试：多轮对话")
    print("输入 'quit' 退出，'history' 查看历史，'clear' 清空历史")
    print("="*40)

    # 先跑一组预设的多轮对话，验证Memory效果
    preset_conversations = [
        "我写过哪些技术相关的笔记？",
        "第一篇讲的是什么内容？",      # 考验Memory：第一篇指上文的第一篇
        "它和第二篇有什么区别？",       # 考验Memory：它和第二篇都需要记住上下文
        "有没有关于情绪的笔记？",       # 切换话题
        "这些笔记是什么时候写的？",     # 考验Memory：这些笔记指上文召回的笔记
    ]

    print("\n【预设多轮对话测试】")
    for q in preset_conversations:
        print(f"\n👤 用户：{q}")
        print("-" * 30)
        answer = rag.chat(q)
        print(f"🤖 AI：{answer}")

    # 展示历史
    rag.show_history()

    # 进入交互模式
    print("\n\n【进入交互模式，可以自由提问】")
    while True:
        user_input = input("\n👤 你：").strip()
        if not user_input:
            continue
        if user_input == "quit":
            break
        if user_input == "history":
            rag.show_history()
            continue
        if user_input == "clear":
            rag.clear_history()
            continue

        answer = rag.chat(user_input)
        print(f"🤖 AI：{answer}")


# ── 主入口 ────────────────────────────────────────
if __name__ == "__main__":
    CURRENT_USER_ID = "3"  # 改成你的user_id

    embeddings  = BGEEmbeddings()
    vectorstore = load_vectorstore(embeddings)
    rag         = RAGWithMemory(
                    vectorstore,
                    user_id=CURRENT_USER_ID,
                    max_history=5
                  )
    test_multi_turn(rag)