# test_format.py（放项目根目录）
import os
from dotenv import load_dotenv
load_dotenv()

from langgraph.checkpoint.memory import InMemorySaver
import app.core.graph as graph_module
graph_module._checkpointer = InMemorySaver()

from app.core.graph import build_graph
from app.storage.sync import get_vectorstore
from langchain.messages import HumanMessage

vectorstore = get_vectorstore()
graph = build_graph(vectorstore)

config = {
    "configurable": {
        "thread_id": "format_test:001",
        "user_id": "6",   # 换成你的真实 user_id
    }
}

result = graph.invoke(
    {
        "messages": [HumanMessage(content="分析一下我最近在关注什么")],
        "user_id": "6",
        "llm_calls": 0,
    },
    config=config,
)

# 直接打印最后一条消息的原始内容
print(result["messages"][-1].content)