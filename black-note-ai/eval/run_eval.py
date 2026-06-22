import os
import json
from tqdm import tqdm
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek
from ragas.llms import LangchainLLMWrapper
from datasets import Dataset
from ragas import evaluate
from ragas.metrics.collections import ContextRecall, ContextPrecision, Faithfulness, AnswerRelevancy

from app.core.rag import make_rag_retriever, rerank_docs
from app.core.prompts import ROVER_SYSTEM_PROMPT
from app.storage.sync import get_vectorstore

load_dotenv()


def main():
    print("正在初始化 RAG 评测管线（多用户模式）...")

    llm = ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        api_base=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0,
    )

    # Qdrant vectorstore（单例）
    vectorstore = get_vectorstore()

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

    print("正在加载黄金测试集...")
    with open("eval/rag_eval_dataset.json", "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    ragas_dataset_list = []
    recall_k_hits = 0
    total_queries  = len(eval_data)

    print(f"开始评测（共 {total_queries} 题）...")
    for item in tqdm(eval_data, desc="Evaluating"):
        query            = item["user_input"]
        expected_note_id = item["expected_note_id"]
        current_user_id  = item.get("expected_user_id")

        retriever    = make_rag_retriever(vectorstore, user_id=current_user_id)
        raw_docs     = retriever.invoke(query)
        reranked     = rerank_docs(query, raw_docs, top_n=6)

        contexts     = [doc.page_content for doc in reranked]
        retrieved_ids = [str(doc.metadata.get("note_id", "")) for doc in reranked]
        context_str  = "\n\n".join([f"笔记片段 {i+1}:\n{t}" for i, t in enumerate(contexts)])

        response = rag_chain.invoke({"context": context_str, "query": query}).content

        if str(expected_note_id) in retrieved_ids:
            recall_k_hits += 1

        ragas_dataset_list.append({
            "user_input":        query,
            "reference":         item["reference"],
            "retrieved_contexts": contexts if contexts else ["暂无相关上下文"],
            "response":          response,
        })

    print(f"\nRecall@K (Top-6): {(recall_k_hits / total_queries) * 100:.2f}%\n")

    print("正在运行 RAGAS 语义评测...")
    hf_dataset   = Dataset.from_list(ragas_dataset_list)
    evaluator_llm = LangchainLLMWrapper(ChatDeepSeek(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        api_base=os.getenv("DEEPSEEK_BASE_URL"),
        temperature=0.0,
    ))
    result = evaluate(
        dataset=hf_dataset,
        metrics=[
            ContextRecall(llm=evaluator_llm),
            ContextPrecision(llm=evaluator_llm),
            Faithfulness(llm=evaluator_llm),
            AnswerRelevancy(llm=evaluator_llm),
        ],
    )

    print("\nRAGAS 评测成绩单：")
    print(result)
    result.to_pandas().to_csv("eval/ragas_evaluation_results.csv", index=False)
    print("详细评测报告已保存至 eval/ragas_evaluation_results.csv")


if __name__ == "__main__":
    main()
