import os
import json
import pymysql
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_deepseek import ChatDeepSeek

# 直接复用你现有的切块和数据库加载逻辑
from app.storage.build_index import load_notes_from_mysql, notes_to_documents

load_dotenv()

# 1. 定义 Ragas v0.4.x 规范的数据结构
class QAPair(BaseModel):
    user_input: str = Field(description="根据文本片段生成的真实用户问题，必须完全可以通过该片段解答。")
    reference: str = Field(description="基于该文本片段提取的一句完整、准确的标准答案，不能脑补。")

# 2. 初始化你正在使用的 DeepSeek 大模型（完美兼容你现有的 .env）
llm = ChatDeepSeek(
    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    api_base=os.getenv("DEEPSEEK_BASE_URL"),
    temperature=0,
)

structured_llm = llm.with_structured_output(QAPair)

# 3. 构建逆向生成的 Prompt
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """你是一个资深的 RAG 系统评测专家。你的任务是根据我提供的【用户笔记片段】，逆向生成用于测试大模型智能助手的高质量问答对。
要求：
1. user_input (问题) 必须像真实用户的提问方式，语气自然。
2. reference (答案) 必须严格基于提供的笔记片段，绝不能编造片段中没有的信息。
3. 如果该片段缺乏实质性信息（如全是分隔符或空壳标题），请生成毫无意义的乱码问题。"""),
    ("user", "【笔记片段】:\n{chunk_text}")
])

chain = prompt_template | structured_llm

def generate_synthetic_data(sample_limit=10):
    print("🚀 开始生成合成测试集...")
    
    # Step A: 从你现有的 MySQL 中拉取笔记 (复用你的代码)
    raw_notes = load_notes_from_mysql()
    # 抽样处理，避免一次性跑太多费钱
    sampled_notes = raw_notes[:sample_limit] 
    
    # Step B: 使用你的 text_cleaner 进行清洗和分块 (复用你的代码)
    docs = notes_to_documents(sampled_notes)
    print(f"✅ 成功加载并切分为 {len(docs)} 个有效 Chunk")

    test_dataset = []

    # Step C: 遍历 Chunk，利用 DeepSeek 逆向生成问答对
    for idx, doc in enumerate(docs):
        chunk_content = doc.page_content
        metadata = doc.metadata
        # 👇【改动 1】：提取 user_id
        note_id = metadata.get("note_id")
        title = metadata.get("title", "无标题")
        user_id = metadata.get("user_id") 
        
        print(f"正在处理 Chunk {idx+1}/{len(docs)} (来源: {title}, 用户: {user_id})...")
        
        try:
            # 调用大模型
            qa_pair = chain.invoke({"chunk_text": chunk_content})
            
            # 过滤掉无法生成有效问题的结果
            if qa_pair.user_input and qa_pair.reference:
                test_dataset.append({
                    "user_input": qa_pair.user_input,      # Ragas 新版字段名
                    "reference": qa_pair.reference,        # Ragas 新版字段名
                    # 下面这两个字段不参与 Ragas 语义打分，但是评测 Recall@K 时必须用到！
                    "expected_note_id": note_id, 
                    "expected_title": title,
                    "expected_user_id": user_id,
                    "source_chunk": chunk_content 
                })
        except Exception as e:
            print(f"⚠️ Chunk {idx+1} 生成失败跳过: {e}")

    # 保存为 JSON 文件
    output_file = "eval/rag_eval_dataset.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(test_dataset, f, ensure_ascii=False, indent=2)
    
    print(f"🎉 生成完毕！共生成 {len(test_dataset)} 条测试数据，已保存至 {output_file}")

if __name__ == "__main__":
    # 你可以修改 sample_limit 来控制拿几篇笔记生成测试集
    generate_synthetic_data(sample_limit=10)