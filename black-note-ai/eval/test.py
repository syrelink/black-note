import os
import json
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from datasets import Dataset
from ragas import evaluate

# ==================== ragas 0.3.9 正确导入方式 ====================
from ragas.metrics import (
    context_recall,
    context_precision,
    faithfulness,
    answer_relevancy,
)

# OpenAI 客户端和 llm_factory
from openai import OpenAI
from ragas.llms import llm_factory
from ragas.embeddings import HuggingFaceEmbeddings

# 你的项目模块
from app.core.rag import make_rag_retriever, rerank_docs
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.storage.embeddings import BGEEmbeddings 

load_dotenv()

def get_real_chroma_path():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path1 = os.path.join(base_dir, "chroma_db")
    path2 = os.path.join(base_dir, "app", "storage", "chroma_db")
    
    if os.path.exists(path1) and os.path.isdir(path1):
        return path1
    elif os.path.exists(path2) and os.path.isdir(path2):
        return path2
    else:
        raise FileNotFoundError(f"🚨 没有找到 chroma_db！")

def main():
    print("🚀 正在初始化 RAG 评测管线 (ragas 0.3.9 版本)...")
    
    # 1. 生成用的 LLM
    llm = ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        api_base=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.1, 
    )
    
    # 2. Chroma 向量库
    persist_directory = get_real_chroma_path()
    collection_name = os.getenv("CHROMA_COLLECTION", "black_note_all")
    vectorstore = Chroma(
        persist_directory=persist_directory,
        embedding_function=BGEEmbeddings(),
        collection_name=collection_name 
    )
    
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", ROVER_SYSTEM_PROMPT + """
        
====================
【相关笔记内容】：
{context}
====================
请严格基于上述检索到的笔记内容回答用户的问题。如果笔记中没有相关信息，请明确告知用户。"""),
        ("user", "{query}")
    ])
    rag_chain = qa_prompt | llm

    # 3. 读取评测数据集（只取前2条测试）
    with open("eval/rag_eval_dataset.json", "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    print(f"\n⚠️ 测试模式：原数据集 {len(eval_data)} 条，仅使用前 2 条...")
    eval_data = eval_data[:2] 

    ragas_dataset_list = []
    recall_k_hits = 0 

    print(f"\n🏃 开始评测（共 {len(eval_data)} 题）...")
    for item in tqdm(eval_data, desc="Evaluating"):
        query = item["user_input"]
        expected_note_id = item["expected_note_id"]
        current_user_id = str(item.get("expected_user_id"))
        
        # RAG 检索 + 重排
        retriever = make_rag_retriever(vectorstore, user_id=current_user_id)
        raw_docs = retriever.invoke(query)
        reranked_docs = rerank_docs(query, raw_docs, top_n=6) 
        
        retrieved_contexts = [doc.page_content for doc in reranked_docs]
        retrieved_note_ids = [str(doc.metadata.get("note_id", "")) for doc in reranked_docs]
        
        context_str = "\n\n".join([f"笔记片段 {i+1}:\n{text}" for i, text in enumerate(retrieved_contexts)])
        
        # 生成回答
        response_msg = rag_chain.invoke({"context": context_str, "query": query})
        actual_response = response_msg.content

        if str(expected_note_id) in retrieved_note_ids:
            recall_k_hits += 1

        ragas_dataset_list.append({
            "user_input": query,
            "reference": item["reference"],           # 必须有这个字段
            "retrieved_contexts": retrieved_contexts if retrieved_contexts else ["暂无相关上下文"],
            "response": actual_response
        })

    print("\n" + "="*50)
    print(f"🎯 物理 Recall@K (Top-6): {(recall_k_hits / len(ragas_dataset_list)) * 100:.2f}%")
    print("="*50 + "\n")

    # ==================== ragas 0.3.9 评测核心 ====================
    print("🧠 正在运行 RAGAS 语义评测 (0.3.9)...")

    hf_dataset = Dataset.from_list(ragas_dataset_list)

    # DeepSeek 客户端
    openai_client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )

    evaluator_llm = llm_factory(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        client=openai_client
    )

    evaluator_embeddings = HuggingFaceEmbeddings(model="BAAI/bge-m3")

    # v0.3.9 正确写法：直接使用导入的对象，不要加括号调用
    metrics = [
        context_recall,
        context_precision,
        faithfulness,
        answer_relevancy,
    ]

    result = evaluate(
        dataset=hf_dataset,
        metrics=metrics,
        llm=evaluator_llm,           # 统一在这里传入 llm
        embeddings=evaluator_embeddings,   # answer_relevancy 需要
    )

    print("\n📊 RAGAS 评测成绩单：")
    print(result)

    # 保存结果
    result_df = result.to_pandas()
    result_df.to_csv("eval/ragas_test_results.csv", index=False)
    print("💾 结果已保存至 eval/ragas_test_results.csv")
    print("✅ ragas 0.3.9 评测完成！")

if __name__ == "__main__":
    main()