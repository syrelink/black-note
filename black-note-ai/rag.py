import os
from typing import Dict
from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnablePassthrough, RunnableWithMessageHistory, RunnableLambda
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

load_dotenv()

# 所有用户的会话历史，key = session_id
_store: Dict[str, InMemoryChatMessageHistory] = {}


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in _store:
        _store[session_id] = InMemoryChatMessageHistory()
    return _store[session_id]


def build_rag_chain(vectorstore, user_id: str):
    """
    构建带历史感知的RAG Chain
    - create_history_aware_retriever：先改写模糊问题再检索
    - RunnableWithMessageHistory：自动管理会话历史
    - user_id过滤：只检索当前用户的笔记
    """
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
        streaming=True,
    )

    # 带user_id过滤的检索器
    retriever = vectorstore.as_retriever(
        search_kwargs={
            "k":      3,
            "filter": {"user_id": user_id}
        }
    )

    # 问题改写Prompt：把模糊问题变成独立完整的检索查询
    contextualize_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "根据聊天历史将当前问题改写成独立完整的检索查询。"
         "只输出改写后的查询，不要回答。"
         "若问题已足够独立，直接输出原问题。"),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    # 回答Prompt
    answer_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是用户的私人笔记助手。\n"
         "规则：\n"
         "1. 严格基于下方笔记内容回答\n"
         "2. 没有相关内容时说'您的笔记中暂无相关内容'\n"
         "3. 回答时注明来自哪篇笔记\n"
         "4. 语言简洁自然\n\n"
         "相关笔记：\n{context}"),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    def format_docs(docs):
        if not docs:
            return "（无相关笔记）"
        return "\n\n".join(
            f"【笔记{i}】标题：{doc.metadata['title']}\n{doc.page_content.strip()}"
            for i, doc in enumerate(docs, 1)
        )

    # 历史感知检索链
    history_aware_retriever = (
        contextualize_prompt
        | llm
        | StrOutputParser()
        | RunnableLambda(lambda q: retriever.invoke(q))
        | format_docs
    )

    # 完整RAG链
    rag_chain = (
        RunnablePassthrough.assign(context=history_aware_retriever)
        | answer_prompt
        | llm
        | StrOutputParser()
    )

    # 包上历史管理
    return RunnableWithMessageHistory(
        rag_chain,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )