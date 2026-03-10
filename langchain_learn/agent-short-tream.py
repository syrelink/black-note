import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain.tools import tool       
from langchain.agents import create_agent 
from langchain.messages import SystemMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
# 向量库
from embeddings import BGEEmbeddings
from langchain_chroma import Chroma
import asyncio
    


load_dotenv()

llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model=os.getenv("DEEPSEEK_MODEL"),
    temperature=0.3,
)
agent = create_agent(
    llm,
    tools=[],
    system_prompt="你是我的贴心小助手！",
    checkpointer=InMemorySaver()
)
config = {"configurable": {"thread_id": "1"}}

# response = agent.stream(
#         input={"messages":[HumanMessage(user_input)]},
#         config=config,
#         stream_mode="values" 
#     )

#     print(response["messages"][-1].content)

async def stream_response(user_input: str):
    print("AI：", end="", flush=True)

    async for event in agent.astream(
        input={"messages": [HumanMessage(content=user_input)]},
        config=config,
        stream_mode=["messages", "updates"]   # 官方最常用组合
    ):
        # 当 stream_mode 是列表时，event 是 (mode, chunk) 元组
        mode, chunk = event

        if mode == "messages":
            # messages 模式下 chunk 是 (message_chunk, metadata)
            msg_chunk, metadata = chunk
            # 只打印文本内容，过滤掉 tool call 的结构部分
            if msg_chunk.content and isinstance(msg_chunk.content, str):
                print(msg_chunk.content, end="", flush=True)

        elif mode == "updates":
            # updates 模式下 chunk 是 {node_name: state_delta}
            for node_name, update in chunk.items():
                if "messages" in update and update["messages"]:
                    last_msg = update["messages"][-1]
                    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                        tc = last_msg.tool_calls[0]
                        print(
                            f"\n  → 调用工具：{tc['name']}  参数：{tc['args']}",
                            flush=True
                        )
                    elif last_msg.content:
                        print(f"\n  ({node_name}) 已生成回复", flush=True)

    print()           # 换行
    print("-" * 50)   # 分隔线，便于阅读

# ────────────────────────────────────────────────
#                    主循环（必须是 async）
# ────────────────────────────────────────────────
async def main():
    print("聊天开始！输入 q / quit / exit 退出")
    while True:
        user_input = input("你：")
        if user_input.lower() in ("q", "quit", "exit"):
            print("再见！")
            break
        await stream_response(user_input)


asyncio.run(main())


