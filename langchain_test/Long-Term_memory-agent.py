from dataclasses import dataclass
from dotenv import load_dotenv
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from typing_extensions import TypedDict
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_core.vectorstores import InMemoryVectorStore
from langgraph.store.memory import InMemoryStore
import os

load_dotenv()

@dataclass
class Context:
    user_id:str

llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model=os.getenv("DEEPSEEK_MODEL"),
    temperature=0.3,
)

# 初始化存储
store = InMemoryStore()
store.put(
    ("users"),
    "user_1",
    {
        "name":"syr",
    }
)

# 用户信息结构的 TypedDict
class UserInfo(TypedDict):
    name: str

# 从存储中获取用户信息的工具
@tool
def get_user_info(user_info: UserInfo, runtime: ToolRuntime[Context]) -> str:
    '''
    保存用户的信息
    当用户提供个人信息的时候，调用此工具
    '''
    store = runtime.store
    user_id = runtime.context.user_id
    store.put(
        ("users"),
        user_id,
        user_info
    )
    return "Successfully saved user info."

# 使用工具和存储创建代理
agent = create_agent(
    llm,
    tools=[get_user_info],
    store=store,
    context_schema=Context
)

# 调用代理
response = agent.invoke(
    {
        "messages":""
    },
    context=Context(user_id="user_2")
)

print(response)  # 代理处理并通过工具保存

save_info = store.get(
    ("users"),
    "user_2"
).value
print(save_info)