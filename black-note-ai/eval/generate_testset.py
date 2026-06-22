import asyncio
import json
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek

from app.storage.build_index import load_notes_from_mongodb, notes_to_documents

load_dotenv()


class QAPair(BaseModel):
    user_input: str = Field(description="根据文本片段生成的真实用户问题，必须完全可以通过该片段解答。")
    reference:  str = Field(description="基于该文本片段提取的一句完整、准确的标准答案，不能脑补。")


llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_BASE_URL"),
    temperature=0,
)

structured_llm = llm.with_structured_output(QAPair)

prompt_template = ChatPromptTemplate.from_messages([
    ("system", """你是一个资深的 RAG 系统评测专家。你的任务是根据我提供的【用户笔记片段】，逆向生成用于测试大模型智能助手的高质量问答对。
要求：
1. user_input (问题) 必须像真实用户的提问方式，语气自然。
2. reference (答案) 必须严格基于提供的笔记片段，绝不能编造片段中没有的信息。
3. 如果该片段缺乏实质性信息（如全是分隔符或空壳标题），请生成毫无意义的乱码问题。"""),
    ("user", "【笔记片段】:\n{chunk_text}")
])

chain = prompt_template | structured_llm


def generate_synthetic_data(sample_limit: int = 10):
    print("开始生成合成测试集...")

    # 从 MongoDB 拉取笔记
    raw_notes = asyncio.run(load_notes_from_mongodb())
    sampled   = raw_notes[:sample_limit]

    docs = notes_to_documents(sampled)
    print(f"成功加载并切分为 {len(docs)} 个有效 Chunk")

    test_dataset = []
    for idx, doc in enumerate(docs):
        meta    = doc.metadata
        note_id = meta.get("note_id")
        title   = meta.get("title", "无标题")
        user_id = meta.get("user_id")
        print(f"处理 Chunk {idx+1}/{len(docs)} (来源: {title}, 用户: {user_id})...")
        try:
            qa = chain.invoke({"chunk_text": doc.page_content})
            if qa.user_input and qa.reference:
                test_dataset.append({
                    "user_input":        qa.user_input,
                    "reference":         qa.reference,
                    "expected_note_id":  note_id,
                    "expected_title":    title,
                    "expected_user_id":  user_id,
                    "source_chunk":      doc.page_content,
                })
        except Exception as e:
            print(f"Chunk {idx+1} 生成失败跳过: {e}")

    output_file = "eval/rag_eval_dataset.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(test_dataset, f, ensure_ascii=False, indent=2)

    print(f"生成完毕！共 {len(test_dataset)} 条，已保存至 {output_file}")


if __name__ == "__main__":
    generate_synthetic_data(sample_limit=10)
