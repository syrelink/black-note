"""
eval/eval_ragas.py - RAG 完整评估（检索端 ranx + 生成端 RAGAS）

【检索端】ranx 库，需要 relevant_note_ids（人工标注）
  Recall@K   top-K 结果里找到了多少相关文档，衡量覆盖率
  NDCG@K     相关文档是否排在靠前位置，衡量排序质量
  MRR@K      第一个相关文档排在第几位，衡量精准度

【生成端】RAGAS 库，需要 ground_truth（人工标注）
  ContextPrecision  检索内容和问题相关吗（需要 ground_truth 做参考基准）
  Faithfulness      回答有没有编造检索文档里没有的内容（不需要 ground_truth）
  AnswerRelevancy   回答有没有真正回答用户的问题（不需要 ground_truth）

【两端分工】
  ranx  → 评估检索器质量，依赖 relevant_note_ids 做精确对比
  RAGAS → 评估生成质量，Judge 模型自动打分

用法：python -m eval.eval_ragas
依赖：pip install ranx ragas sentence-transformers
"""

import asyncio
import json
import os
import warnings
from typing import List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

# ranx：信息检索评估库
# Qrels = 人工标注的标准答案（哪些文档相关）
# Run   = 检索系统返回的结果（按排名顺序）
from ranx import Qrels, Run, evaluate

# RAGAS：生成质量评估库
# ragas.metrics.collections + ascore 是当前版本能正常运行的方式
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
from ragas.embeddings import HuggingFaceEmbeddings
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, Faithfulness

from app.core.rag import make_rag_retriever, rerank_docs
from app.storage.embeddings import _get_model
from app.storage.sync import get_vectorstore

load_dotenv()

LABELED_DATA_PATH = "eval/labeled_data.json"
K = 6  # top-K，和线上 search_notes 的 limit 保持一致

# ══════════════════════════════════════════════════════════════
# 1. 加载人工标注数据
# ══════════════════════════════════════════════════════════════

def load_labeled_data() -> List[dict]:
    """
    加载标注文件，每条格式：
    {
        "question":          用户问题
        "user_id":           用于构建该用户的检索器
        "relevant_note_ids": 相关笔记 ID 列表，ranx 检索端评估用
        "ground_truth":      人工写的参考答案，RAGAS ContextPrecision 用
    }
    """
    if not os.path.exists(LABELED_DATA_PATH):
        raise FileNotFoundError(
            f"找不到标注文件 {LABELED_DATA_PATH}\n"
            f"请先运行：python eval/annotation_tool.py"
        )
    with open(LABELED_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    print(f"加载标注数据：{len(data)} 条")
    return data


# ══════════════════════════════════════════════════════════════
# 2. 真实检索（检索端和生成端共用）
# ══════════════════════════════════════════════════════════════

def do_retrieve(retriever_factory, question: str, user_id: str) -> list:
    """
    用真实向量库检索，返回 Document 列表。
    和线上 search_notes 逻辑完全一致：
      1. 按 user_id 构建检索器（过滤前置，只检索该用户文档）
      2. EnsembleRetriever（BM25 + 向量）混合检索
      3. rerank 重排序
      4. 取 top-K
    检索端和生成端都调用这个函数，保证两端用的是同一批检索结果。
    """
    retriever = retriever_factory(user_id)
    raw_docs  = retriever.invoke(question)
    return rerank_docs(question, raw_docs, top_n=K)


# ══════════════════════════════════════════════════════════════
# 3. 真实生成
# ══════════════════════════════════════════════════════════════

def generate_answer(llm, question: str, docs: list) -> str:
    """
    基于检索文档生成回答。
    system prompt 和线上 Rover 保持一致，评估的是真实线上效果。
    """
    if not docs:
        return "抱歉，没有找到相关笔记。"

    context_text = "\n\n---\n\n".join(doc.page_content for doc in docs)
    messages = [
        SystemMessage(content=(
            "你是用户的笔记助手 Rover。"
            "请严格基于以下笔记内容回答用户问题，不得编造笔记中没有的内容。\n\n"
            f"笔记内容：\n{context_text}"
        )),
        HumanMessage(content=question),
    ]
    return llm.invoke(messages).content


# ══════════════════════════════════════════════════════════════
# 4. 检索端评估：ranx 计算 Recall / NDCG / MRR
# ══════════════════════════════════════════════════════════════

def evaluate_retrieval(retriever_factory, labeled_data: List[dict]) -> dict:
    """
    用 ranx 计算检索端三个指标。

    原理：
      把检索结果（Run）和人工标注（Qrels）做对比：

      Recall@K  命中数 / 总相关数
                0.8 表示 80% 的相关笔记被检索到，越高越好

      NDCG@K    相关文档排越靠前得分越高（log 衰减惩罚靠后排名）
                1.0 表示所有相关文档都排在最前面，越高越好

      MRR@K     第一个相关文档排名倒数的均值
                MRR=1.0 表示每次第一个结果就是相关的，越高越好

    ranx 数据格式：
      Qrels：{query_id: {note_id: 1}}      1 表示相关（二值）
      Run：  {query_id: {note_id: score}}  score 用排名倒数
                                           第1名=1.0，第2名=0.5，第3名=0.33...
    """
    print(f"\n{'─' * 55}")
    print(f"📊 检索端评估（ranx）Recall / NDCG / MRR @{K}")
    print(f"{'─' * 55}")

    qrels_dict = {}
    run_dict   = {}

    for i, item in enumerate(labeled_data):
        query_id     = f"q{i}"
        question     = item["question"]
        user_id      = item["user_id"]
        relevant_ids = item.get("relevant_note_ids", [])

        # relevant_note_ids 是 ranx 的 ground truth
        # 没有标注的条目跳过，无法计算检索端指标
        if not relevant_ids:
            print(f"  ⚠️ 跳过（无 relevant_note_ids）：{question}")
            continue

        # Qrels：人工标注的相关文档，权重为 1（二值相关性）
        qrels_dict[query_id] = {nid: 1 for nid in relevant_ids}

        # 真实检索
        docs = do_retrieve(retriever_factory, question, user_id)

        # Run：排名倒数作为分数，ranx 要求分数越高表示越相关
        run_dict[query_id] = {
            doc.metadata["note_id"]: 1.0 / (rank + 1)
            for rank, doc in enumerate(docs)
            if doc.metadata.get("note_id")
        }

        hit_ids = [
            doc.metadata["note_id"] for doc in docs
            if doc.metadata.get("note_id") in set(relevant_ids)
        ]
        print(f"  ✓ {question[:28]:<28}  命中={hit_ids}")

    if not qrels_dict:
        print("  没有有效的检索评估数据")
        return {}

    qrels = Qrels(qrels_dict)
    run   = Run(run_dict)

    # ranx 一行计算所有指标，返回各指标的均值
    results = evaluate(
        qrels, run,
        [f"recall@{K}", f"ndcg@{K}", f"mrr@{K}"],
    )

    scores = {
        f"Recall@{K}": round(results[f"recall@{K}"], 4),
        f"NDCG@{K}":   round(results[f"ndcg@{K}"],   4),
        f"MRR@{K}":    round(results[f"mrr@{K}"],    4),
    }

    print(f"\n  Recall@{K}  = {scores[f'Recall@{K}']}  （覆盖率）")
    print(f"  NDCG@{K}    = {scores[f'NDCG@{K}']}  （排序质量）")
    print(f"  MRR@{K}     = {scores[f'MRR@{K}']}  （精准度）")

    return scores


# ══════════════════════════════════════════════════════════════
# 5. 构建 RAGAS EvaluationDataset
# ══════════════════════════════════════════════════════════════

def build_ragas_dataset(
    labeled_data: List[dict],
    retriever_factory,
    llm,
) -> tuple[EvaluationDataset, List[dict]]:
    """
    对每条标注数据做真实检索 + 真实生成，组装成 RAGAS 标准格式。

    SingleTurnSample 字段：
      user_input          用户问题
      retrieved_contexts  检索文档片段（List[str]，不是 List[Document]）
      response            模型生成的回答
      reference           参考答案（ground_truth），只有 ContextPrecision 需要
    """
    samples  = []
    raw_rows = []
    skipped  = 0

    print("\n正在构建评估数据集...")
    for item in labeled_data:
        question     = item["question"]
        user_id      = item["user_id"]
        ground_truth = item["ground_truth"]

        # 真实检索，和线上 search_notes 逻辑完全一致
        docs = do_retrieve(retriever_factory, question, user_id)
        if not docs:
            print(f"  跳过（无检索结果）：{question}")
            skipped += 1
            continue

        # RAGAS 要求 retrieved_contexts 是 List[str]，不是 List[Document]
        # 用完整内容，不截断，让 Judge 看到完整信息，评分更准确
        contexts = [doc.page_content for doc in docs]

        # 真实生成
        answer = generate_answer(llm, question, docs)

        samples.append(SingleTurnSample(
            user_input=question,
            retrieved_contexts=contexts,
            response=answer,
            reference=ground_truth,
        ))
        raw_rows.append({
            "question":     question,
            "contexts":     contexts,
            "answer":       answer,
            "ground_truth": ground_truth,
        })
        print(f"  done: {question[:30]}")

    if skipped:
        print(f"  跳过 {skipped} 条（无检索结果）")

    dataset = EvaluationDataset(samples=samples)
    print(f"数据集构建完成：{len(samples)} 条有效样本")
    return dataset, raw_rows


# ══════════════════════════════════════════════════════════════
# 6. RAGAS 评估
# ══════════════════════════════════════════════════════════════

async def run_ragas_evaluation(dataset: EvaluationDataset) -> dict:
    """
    用 collections metrics 的 ascore() 并发评估所有样本。

    三个指标：
      ContextPrecision  检索内容和问题相关吗（用 ground_truth 做参考基准）
      Faithfulness      回答忠实于检索内容，没有编造
      AnswerRelevancy   回答真正回答了用户的问题

    ascore 签名（从源码确认）：
      ContextPrecision : ascore(user_input, reference, retrieved_contexts)
      Faithfulness     : ascore(user_input, response, retrieved_contexts)
      AnswerRelevancy  : ascore(user_input, response)
    返回 MetricResult(value, reason)

    Judge LLM 用 DEEPSEEK，不需要 OpenAI key。
    AnswerRelevancy 需要 embeddings 做余弦相似度，复用已有的 bge-m3。
    """
    client = AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )
    evaluator_llm = llm_factory(os.getenv("DEEPSEEK_MODEL"), client=client)

    # AnswerRelevancy 需要 embeddings，复用已有的 bge-m3，不依赖外部服务
    embeddings = HuggingFaceEmbeddings(model="BAAI/bge-m3")

    cp_metric = ContextPrecision(llm=evaluator_llm)
    ff_metric = Faithfulness(llm=evaluator_llm)
    ar_metric = AnswerRelevancy(llm=evaluator_llm, embeddings=embeddings)

    async def score_sample(sample: SingleTurnSample):
        """对单条样本并发评估三个指标，任意一个失败返回 None 不影响其他"""
        try:
            cp = await cp_metric.ascore(
                user_input=sample.user_input,
                reference=sample.reference,
                retrieved_contexts=sample.retrieved_contexts,
            )
            cp_score = cp.value
        except Exception as e:
            print(f"CP 失败: {sample.user_input[:30]}... → {e}")
            cp_score = None

        try:
            ff = await ff_metric.ascore(
                user_input=sample.user_input,
                response=sample.response,
                retrieved_contexts=sample.retrieved_contexts,
            )
            ff_score = ff.value
        except Exception as e:
            print(f"FF 失败: {sample.user_input[:30]}... → {e}")
            ff_score = None

        try:
            ar = await ar_metric.ascore(
                user_input=sample.user_input,
                response=sample.response,
            )
            ar_score = ar.value
        except Exception as e:
            print(f"AR 失败: {sample.user_input[:30]}... → {e}")
            ar_score = None

        return cp_score, ff_score, ar_score

    # asyncio.gather 并发评估所有样本，比串行循环快
    print("\n正在并发评估所有样本...")
    tasks      = [score_sample(sample) for sample in dataset.samples]
    all_scores = await asyncio.gather(*tasks, return_exceptions=True)

    cp_scores, ff_scores, ar_scores = [], [], []
    for res in all_scores:
        if isinstance(res, Exception):
            cp_scores.append(None)
            ff_scores.append(None)
            ar_scores.append(None)
        else:
            cp, ff, ar = res
            cp_scores.append(cp)
            ff_scores.append(ff)
            ar_scores.append(ar)

    # 计算均值，忽略 None（评估失败的条目不影响整体分数）
    valid_cp = [v for v in cp_scores if v is not None]
    valid_ff = [v for v in ff_scores if v is not None]
    valid_ar = [v for v in ar_scores if v is not None]

    aggregated = {
        "context_precision": round(sum(valid_cp) / len(valid_cp), 3) if valid_cp else None,
        "faithfulness":      round(sum(valid_ff) / len(valid_ff), 3) if valid_ff else None,
        "answer_relevancy":  round(sum(valid_ar) / len(valid_ar), 3) if valid_ar else None,
    }

    print("\n聚合分数：")
    for k, v in aggregated.items():
        print(f"  {k:25} = {v if v is not None else 'N/A'}")

    return aggregated


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

async def main():
    labeled_data = load_labeled_data()

    print("\n初始化模型和向量库...")
    _get_model()  # 预热 bge-m3，避免第一次请求时才加载

    # 用于生成回答的 LLM（线上同款模型）
    llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL"),
    )

    vectorstore = get_vectorstore()

    # retriever_factory：按 user_id 动态构建检索器
    # lambda 把 vectorstore 提前绑定，对外只暴露 user_id 参数
    # _retriever_cache 保证同一用户只构建一次 BM25 索引
    retriever_factory = lambda uid: make_rag_retriever(vectorstore, user_id=uid)

    # ── 检索端评估（ranx）────────────────────────────────────
    retrieval_scores = evaluate_retrieval(retriever_factory, labeled_data)

    # ── 生成端评估（RAGAS）───────────────────────────────────
    print(f"\n{'─' * 55}")
    print("📊 生成端评估（RAGAS）")
    print(f"{'─' * 55}")
    dataset, raw_rows = build_ragas_dataset(labeled_data, retriever_factory, llm)

    if len(dataset.samples) == 0:
        print("无有效数据，退出")
        return

    generation_scores = await run_ragas_evaluation(dataset)

    # ── 保存完整结果 ──────────────────────────────────────────
    output = {
        "retrieval":  retrieval_scores,
        "generation": generation_scores,
        "eval_rows":  raw_rows,
    }
    with open("eval/eval_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    # ── 简历量化指标汇总 ──────────────────────────────────────
    cp = generation_scores.get("context_precision")
    ff = generation_scores.get("faithfulness")
    ar = generation_scores.get("answer_relevancy")

    print("\n" + "=" * 55)
    print("📋 简历量化指标汇总")
    print("=" * 55)
    print(f"\n  【检索端（ranx）】")
    print(f"  Recall@{K}          : {retrieval_scores.get(f'Recall@{K}', 'N/A')}  （覆盖率）")
    print(f"  NDCG@{K}            : {retrieval_scores.get(f'NDCG@{K}',   'N/A')}  （排序质量）")
    print(f"  MRR@{K}             : {retrieval_scores.get(f'MRR@{K}',    'N/A')}  （精准度）")
    print(f"\n  【生成端（RAGAS）】")
    # f'{cp:.3f}' 是格式化浮点数，如果 cp 为 None 则显示 N/A
    print(f"  ContextPrecision  : {f'{cp:.3f}' if cp is not None else 'N/A'}  （检索相关性）")
    print(f"  Faithfulness      : {f'{ff:.3f}' if ff is not None else 'N/A'}  （忠实性）")
    print(f"  AnswerRelevancy   : {f'{ar:.3f}' if ar is not None else 'N/A'}  （切题度）")
    print("=" * 55)
    print("📁 完整结果已保存到 eval/eval_result.json")


if __name__ == "__main__":
    asyncio.run(main())