"""
tests/eval_rag.py - RAG 真实数据评估

【评估框架】RAG Triad（大厂标准）
  1. Context Relevancy  上下文相关性  检索到的文档和问题相关吗？
  2. Faithfulness       忠实性        回答有没有超出文档内容编造？
  3. Answer Relevancy   回答相关性    回答有没有真正回答问题？
  + Rerank 提升率       rerank 前后正确文档排名是否提升？

【数据来源】
  - 问题          → 手动设计的评估问题集
  - contexts      → 真实向量库检索结果（search_notes 的返回）
  - answer        → 真实 LLM 基于检索结果生成的回答
  - ground_truth  → 从 MySQL 取对应笔记的原始内容作为参考

【为什么不用假数据】
  假数据评估的是假场景，数字好看但没有意义。
  用真实检索结果才能反映线上实际质量。

用法：
  cd black-note-ai
  python -m tests.eval_rag
"""

import json
import os
import pymysql

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from datasets import Dataset

# 复用项目里已有的模块，不重复造轮子
from app.storage.sync import get_vectorstore
from app.storage.embeddings import warmup
from app.core.rag import make_rag_retriever, rerank_docs

load_dotenv()

# ── 数据库配置（复用 sync.py 的配置）─────────────────────────
DB_CONFIG = {
    "host":     os.getenv("MYSQL_HOST",     "127.0.0.1"),
    "port":     int(os.getenv("MYSQL_PORT", "3306")),
    "user":     os.getenv("MYSQL_USER",     "root"),
    "password": os.getenv("MYSQL_PASSWORD", "123456"),
    "database": os.getenv("MYSQL_DB",       "black_note"),
    "charset":  "utf8mb4",
}

# ── 评估问题集 ────────────────────────────────────────────────
# 设计原则：
#   1. 覆盖真实用户场景，不要出现向量库里不存在的内容
#   2. 每个问题对应一个 user_id，只在该用户的笔记里检索
#   3. ground_truth 从 MySQL 里取，不手动填写，保证真实性

EVAL_QUESTIONS = [
    {
        "question": "找找我写过关于 LangChain 的笔记",
        "user_id": "6",   # ← 换成真实 user_id
    },
    {
        "question": "我有没有写过关于面试的笔记",
        "user_id": "6",
    },
    {
        "question": "找找我记录过的 Python 相关内容",
        "user_id": "6",
    },
    {
        "question": "我写过什么关于学习方法的笔记",
        "user_id": "6",
    },
    {
        "question": "有没有关于项目经验的笔记",
        "user_id": "6",
    },
]


# ══════════════════════════════════════════════════════════════
# Step 1: 真实检索
# ══════════════════════════════════════════════════════════════
def retrieve_contexts(retriever, question: str, user_id: str, limit: int = 6) -> list[str]:
    """
    用真实向量库检索，过滤当前用户，经过 rerank 后返回 snippet 列表。
    这和 tools.py 里 search_notes 的逻辑完全一致，保证评估环境和线上一致。
    """
    raw_docs = retriever.invoke(question)

    # 过滤当前用户且未删除的文档（和 search_notes 保持一致）
    user_docs = [
        doc for doc in raw_docs
        if str(doc.metadata.get("user_id")) == str(user_id)
        and doc.metadata.get("is_deleted", 0) == 0
    ]

    if not user_docs:
        return []

    reranked = rerank_docs(question, user_docs, top_n=limit)

    return [
        doc.page_content[:400] + "..." if len(doc.page_content) > 400 else doc.page_content
        for doc in reranked
    ]


# ══════════════════════════════════════════════════════════════
# Step 2: 生成回答
# ══════════════════════════════════════════════════════════════
def generate_answer(model, question: str, contexts: list[str]) -> str:
    """
    基于检索到的真实文档生成回答。
    system prompt 和线上 Rover 保持一致，评估的就是线上真实效果。
    """
    if not contexts:
        return "抱歉，没有找到相关笔记。"

    context_text = "\n\n---\n\n".join(contexts)

    messages = [
        SystemMessage(content=(
            "你是用户的笔记助手 Rover。"
            "请严格基于以下笔记内容回答用户问题，不得编造笔记中没有的内容。\n\n"
            f"笔记内容：\n{context_text}"
        )),
        HumanMessage(content=question),
    ]

    response = model.invoke(messages)
    return response.content


# ══════════════════════════════════════════════════════════════
# Step 3: 从 MySQL 取 ground_truth
# ══════════════════════════════════════════════════════════════
def fetch_ground_truth(question: str, user_id: str) -> str:
    """
    从 MySQL 取该用户最相关的笔记原文作为 ground_truth。

    做法：先用 MySQL LIKE 粗筛，取标题或内容匹配的笔记。
    这不是精确匹配，而是给 RAGAS 一个参考基准。
    实际项目中可以人工标注更准确的 ground_truth，但自动化取值
    已经能反映大部分场景的质量。
    """
    # 从问题里提取关键词（简单取最后几个词）
    keywords = question.replace("找找", "").replace("我写过", "").replace(
        "关于", "").replace("的笔记", "").replace("有没有", "").strip()

    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(
                """
                SELECT title, content
                FROM note
                WHERE user_id = %s
                  AND is_deleted = 0
                  AND (title LIKE %s OR content LIKE %s)
                ORDER BY created_at DESC
                LIMIT 3
                """,
                (user_id, f"%{keywords}%", f"%{keywords}%"),
            )
            rows = cursor.fetchall()

        if not rows:
            return f"用户没有写过关于「{keywords}」的笔记"

        # 把找到的笔记标题拼成 ground_truth
        titles = [row["title"] or "无标题" for row in rows]
        return f"用户写过以下相关笔记：{'、'.join(titles)}"

    except Exception as e:
        print(f"获取 ground_truth 失败：{e}")
        return ""
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════
# Step 4: Rerank 提升率评估
# ══════════════════════════════════════════════════════════════
def evaluate_rerank(retriever, questions: list[dict]) -> dict:
    """
    对比 rerank 前后，相关文档的平均排名变化。

    做法：
      1. 取 rerank 前的排名（原始检索顺序）
      2. 取 rerank 后的排名
      3. 如果相关文档排名提升，说明 rerank 有效

    判断"相关"的标准：文档的 note_id 在 ground_truth 里出现过。
    """
    rank_improvements = []

    conn = pymysql.connect(**DB_CONFIG)

    for item in questions:
        question = item["question"]
        user_id = item["user_id"]

        raw_docs = retriever.invoke(question)
        user_docs = [
            doc for doc in raw_docs
            if str(doc.metadata.get("user_id")) == str(user_id)
            and doc.metadata.get("is_deleted", 0) == 0
        ]

        if len(user_docs) < 2:
            continue

        # rerank 后的顺序
        reranked = rerank_docs(question, user_docs, top_n=len(user_docs))

        # 取关键词，从 MySQL 找相关 note_id 作为"正确答案"
        keywords = question.replace("找找", "").replace("我写过", "").replace(
            "关于", "").replace("的笔记", "").replace("有没有", "").strip()

        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id FROM note
                    WHERE user_id=%s AND is_deleted=0
                      AND (title LIKE %s OR content LIKE %s)
                    LIMIT 5
                    """,
                    (user_id, f"%{keywords}%", f"%{keywords}%"),
                )
                relevant_ids = {str(r["id"]) for r in cursor.fetchall()}
        except Exception:
            continue

        if not relevant_ids:
            continue

        # 计算 rerank 前相关文档的平均排名（越小越好，从 1 开始）
        before_ranks = [
            i + 1 for i, doc in enumerate(user_docs)
            if doc.metadata.get("note_id") in relevant_ids
        ]

        # 计算 rerank 后相关文档的平均排名
        after_ranks = [
            i + 1 for i, doc in enumerate(reranked)
            if doc.metadata.get("note_id") in relevant_ids
        ]

        if before_ranks and after_ranks:
            before_avg = sum(before_ranks) / len(before_ranks)
            after_avg = sum(after_ranks) / len(after_ranks)
            improvement = before_avg - after_avg  # 正数表示排名提升
            rank_improvements.append({
                "question": question,
                "before_avg_rank": round(before_avg, 1),
                "after_avg_rank": round(after_avg, 1),
                "improvement": round(improvement, 1),
            })

    conn.close()

    if not rank_improvements:
        return {"rerank_improvement": "数据不足", "details": []}

    avg_improvement = sum(r["improvement"] for r in rank_improvements) / len(rank_improvements)
    improved_count = sum(1 for r in rank_improvements if r["improvement"] > 0)

    return {
        "平均排名提升": round(avg_improvement, 2),   # 正数越大越好
        "提升比例": f"{improved_count}/{len(rank_improvements)}",
        "details": rank_improvements,
    }


# ══════════════════════════════════════════════════════════════
# Step 5: RAGAS 评估
# ══════════════════════════════════════════════════════════════
def run_ragas_evaluation(retriever, model, questions: list[dict]) -> dict:
    """
    构建真实评估数据集并运行 RAGAS。
    每条数据都来自真实检索和真实生成，不使用任何硬编码内容。
    """
    try:
        from ragas import evaluate
        from ragas.metrics import context_relevancy, faithfulness, answer_relevancy
    except ImportError:
        print("❌ 请先安装 RAGAS：pip install ragas")
        return {}

    eval_rows = []
    print("\n📥 正在构建真实评估数据集...")

    for item in questions:
        question = item["question"]
        user_id = item["user_id"]

        print(f"  处理：{question}")

        # 真实检索
        contexts = retrieve_contexts(retriever, question, user_id)
        if not contexts:
            print(f"    ⚠️  未检索到相关文档，跳过")
            continue

        # 真实生成
        answer = generate_answer(model, question, contexts)

        # 从 MySQL 取 ground_truth
        ground_truth = fetch_ground_truth(question, user_id)

        eval_rows.append({
            "question": question,
            "contexts": contexts,        # 真实检索到的文档片段列表
            "answer": answer,            # 真实 LLM 生成的回答
            "ground_truth": ground_truth, # 从 MySQL 取的参考答案
        })

    if not eval_rows:
        print("❌ 没有有效的评估数据")
        return {}

    print(f"\n✅ 数据集构建完成，共 {len(eval_rows)} 条")

    dataset = Dataset.from_list(eval_rows)

    # 配置 RAGAS 使用你项目里已有的模型
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import OpenAIEmbeddings

    ragas_llm = LangchainLLMWrapper(model)

    print("\n🔍 正在运行 RAGAS 评估（需要几分钟）...")
    result = evaluate(
        dataset,
        metrics=[context_relevancy, faithfulness, answer_relevancy],
        llm=ragas_llm,
    )

    return {
        "上下文相关性 (Context Relevancy)": round(result["context_relevancy"], 3),
        "忠实性 (Faithfulness)":           round(result["faithfulness"], 3),
        "回答相关性 (Answer Relevancy)":    round(result["answer_relevancy"], 3),
        "原始数据集": eval_rows,  # 保存用于人工抽查
    }


# ══════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("🚀 初始化模型和向量库...")
    warmup()  # 预热 bge-m3

    model = ChatOpenAI(
        model=os.getenv("MIMO_MODEL"),
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL"),
    )

    vectorstore = get_vectorstore()
    retriever = make_rag_retriever(vectorstore)

    # ── Rerank 提升率评估 ──────────────────────────────────────
    print("\n📊 评估 Rerank 提升率...")
    rerank_result = evaluate_rerank(retriever, EVAL_QUESTIONS)
    print(f"\nRerank 评估结果：")
    print(f"  平均排名提升：{rerank_result.get('平均排名提升', 'N/A')}")
    print(f"  提升比例：    {rerank_result.get('提升比例', 'N/A')}")
    for detail in rerank_result.get("details", []):
        arrow = "↑" if detail["improvement"] > 0 else "↓" if detail["improvement"] < 0 else "→"
        print(f"  {arrow} {detail['question'][:20]}... "
              f"rerank前={detail['before_avg_rank']} "
              f"rerank后={detail['after_avg_rank']}")

    # ── RAGAS 评估 ─────────────────────────────────────────────
    print("\n📊 评估 RAG 质量（RAGAS）...")
    ragas_result = run_ragas_evaluation(retriever, model, EVAL_QUESTIONS)

    if ragas_result:
        print(f"\nRAGAS 评估结果：")
        for k, v in ragas_result.items():
            if k != "原始数据集":
                print(f"  {k}: {v}")

    # ── 保存完整结果 ───────────────────────────────────────────
    output = {
        "rerank": rerank_result,
        "ragas": {k: v for k, v in ragas_result.items() if k != "原始数据集"},
        "eval_dataset": ragas_result.get("原始数据集", []),
    }

    with open("eval_rag_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print("\n📁 完整结果已保存到 eval_rag_result.json")

    # ── 简历用数字汇总 ─────────────────────────────────────────
    print("\n" + "=" * 50)
    print("📋 简历量化指标汇总")
    print("=" * 50)
    if ragas_result:
        print(f"  Context Relevancy : {ragas_result.get('上下文相关性 (Context Relevancy)', 'N/A')}")
        print(f"  Faithfulness      : {ragas_result.get('忠实性 (Faithfulness)', 'N/A')}")
        print(f"  Answer Relevancy  : {ragas_result.get('回答相关性 (Answer Relevancy)', 'N/A')}")
    print(f"  Rerank 平均排名提升: {rerank_result.get('平均排名提升', 'N/A')}")
    print(f"  Rerank 提升比例   : {rerank_result.get('提升比例', 'N/A')}")
    print("=" * 50)