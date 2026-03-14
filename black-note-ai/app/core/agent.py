"""
私人笔记 Agent：整合 RAG + 精确工具
- 支持语义/关键词搜索笔记（RAG tool）
- 支持按 ID 读完整笔记、列出所有笔记
- 使用 DeepSeek LLM + 记忆
"""

import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, text
from app.core.tools import make_tools
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.sqlite import SqliteSaver

load_dotenv()

# MySQL 连接
engine = create_engine(
    os.getenv("MYSQL_URL", "mysql+pymysql://root:123456@127.0.0.1/black_note"),
    pool_size=5,
    max_overflow=10,
)

# 全局记忆
# 说明：
# - 文件会自动生成在项目根目录
# - 服务重启后记忆依然存在
# - 每个 user_id 独立存储（thread_id = user_id）
_checkpointer = SqliteSaver.from_conn_string("./checkpoints.db")


def build_agent(vectorstore, user_id: str):
    """
    构建 Agent
    - thread_id 可用于区分同一用户的不同会话（默认用 user_id 作为 thread_id）
    """
    llm = ChatOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
        model=os.getenv("DEEPSEEK_MODEL"),
        temperature=0.3,
        streaming=True,
    )

    tools = make_tools(vectorstore, user_id)

    system_prompt = SystemMessage(content="""你是用户的私人笔记助手，同时也是一个专业、美观、易读的 Markdown 输出专家。

    - 工具只提供原始资料，你必须自己根据用户需求智能整理。
    - 所有回答**必须使用标准 Markdown 格式**，并智能分行。
    - 保持简洁美观，用户一眼就能看懂。

    开始回答时，请严格按照 Markdown 风格输出，保持专业、美观、智能分行。""")

    # 使用 create_agent（LangChain 当前推荐方式）
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=_checkpointer,
    )

    # 如果想用 LangGraph 更高级控制（推荐长期迁移），可改成：
    # from langgraph.prebuilt import create_react_agent
    # 但当前 create_agent 已足够，且兼容记忆

    return agent | StrOutputParser()