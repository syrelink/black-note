import os
from dotenv import load_dotenv
from langchain.messages import HumanMessage, SystemMessage
from sqlalchemy import create_engine, text
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()
CURRENT_USER_ID = 6

# LLM
llm = ChatOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL"),
    model=os.getenv("DEEPSEEK_MODEL"),
    temperature=0.3,
)

prompt = ChatPromptTemplate.from_messages([
    SystemMessage("你是一个冷酷的杀手"),
    HumanMessage("{input}")
])

chain = prompt | llm | StrOutputParser()

for chunk in chain.stream({"input":"你好"}):
    print(chunk,end="",flush=True)

