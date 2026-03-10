from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from typing import Annotated, Sequence
from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
    
# 1. 定义状态
class AgentState(dict):
    messages: Annotated[Sequence[BaseMessage], "add_messages"]

# 2. 工具示例
@tool
def search(query: str) -> str:
    return "搜索结果"

tools = [search]
tool_node = ToolNode(tools)

# 3. Agent 节点（用纯 LCEL 实现思考）
def agent(state: AgentState):
    prompt = ChatPromptTemplate.from_messages([("system", "你是助手"), ("human", "{input}")])
    chain = prompt | llm  # 纯 LCEL 子链
    response = chain.invoke({"input": state["messages"][-1].content})
    return {"messages": [response]}

# 4. 构建图
workflow = StateGraph(state_schema=AgentState)
workflow.add_node("agent", agent)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", tools_condition)  # 如果有 tool_call → tools
workflow.add_edge("tools", "agent")  # 工具后回 agent

graph = workflow.compile()

# 5. 调用
response = graph.invoke({"messages": [("human", "搜索天气")]})