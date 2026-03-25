import os
import json
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from ragas.llms import LangchainLLMWrapper
from datasets import Dataset
from ragas import evaluate
from ragas.metrics.collections import ContextRecall, ContextPrecision, Faithfulness, AnswerRelevancy

from app.core.rag import make_rag_retriever, rerank_docs
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.storage.embeddings import BGEEmbeddings

load_dotenv()

def main():
    print("🚀 正在初始化 RAG 评测管线 (多用户模式)...")
    
    llm = ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        api_base=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0, 
    )
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
    persist_directory = os.path.join(base_dir, "chroma_db")
    
    vectorstore = Chroma(
        persist_directory=persist_directory,
        embedding_function=BGEEmbeddings(),
        collection_name="black_note_all"
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

    print("📚 正在加载黄金测试集...")
    with open("eval/rag_eval_dataset.json", "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    ragas_dataset_list = []
    recall_k_hits = 0 
    total_queries = len(eval_data)

    print(f"🏃 开始闭卷考试（共 {total_queries} 题）...")
    for item in tqdm(eval_data, desc="Evaluating"):
        query = item["user_input"]
        expected_note_id = item["expected_note_id"]
        
        # 👇【改动 3】：从数据集中提取该题目对应的 user_id
        current_user_id = item.get("expected_user_id")
        
        # 👇【改动 4】：动态构建或获取缓存的检索器
        retriever = make_rag_retriever(vectorstore, user_id=current_user_id)
        
        # 执行检索与重排
        raw_docs = retriever.invoke(query)
        reranked_docs = rerank_docs(query, raw_docs, top_n=6) 
        
        retrieved_contexts = [doc.page_content for doc in reranked_docs]
        retrieved_note_ids = [str(doc.metadata.get("note_id", "")) for doc in reranked_docs]
        
        context_str = "\n\n".join([f"笔记片段 {i+1}:\n{text}" for i, text in enumerate(retrieved_contexts)])
        
        response_msg = rag_chain.invoke({
            "context": context_str,
            "query": query
        })
        actual_response = response_msg.content

        if str(expected_note_id) in retrieved_note_ids:
            recall_k_hits += 1

        ragas_dataset_list.append({
            "user_input": query,
            "reference": item["reference"],
            "retrieved_contexts": retrieved_contexts if retrieved_contexts else ["暂无相关上下文"],
            "response": actual_response
        })

    print("\n" + "="*40)
    print(f"🎯 物理命中指标 Recall@K (Top-6): {(recall_k_hits / total_queries) * 100:.2f}%")
    print("="*40 + "\n")

    print("🧠 正在呼叫大模型裁判运行 RAGAS 语义评测...")
    hf_dataset = Dataset.from_list(ragas_dataset_list)

    llm = ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        api_base=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.0
    )
    evaluator_llm = LangchainLLMWrapper(llm)
    result = evaluate(
        dataset=hf_dataset,
        metrics=[
            ContextRecall(llm=evaluator_llm), 
            ContextPrecision(llm=evaluator_llm), 
            Faithfulness(llm=evaluator_llm), 
            AnswerRelevancy(llm=evaluator_llm)  
        ],
    )

    print("\n📊 RAGAS 评测最终成绩单：")
    print(result)
    
    result_df = result.to_pandas()
    result_df.to_csv("eval/ragas_evaluation_results.csv", index=False)
    print("💾 详细评测报告已保存至 eval/ragas_evaluation_results.csv")

if __name__ == "__main__":
    main()