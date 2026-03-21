"""
diagnose_semantic.py
深度诊断：semantic_search_notes + cross_note_analysis + 底层检索为什么返回空
"""

import json
from app.core.tools import make_tools
from app.storage.sync import get_vectorstore
from app.core.rag import rerank_docs   # 直接导入 rerank
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

print("🚀 开始语义搜索深度诊断...\n")

vectorstore = get_vectorstore()
tools, tools_by_name = make_tools(vectorstore)
TEST_USER_ID = "6"          # ← 你的用户ID
QUERY = "最近的笔记"       # 测试查询

_ENGINE = create_engine(os.getenv("MYSQL_URL"))

# ====================== 1. 原始 rag_retriever（底层向量检索） ======================
print("=== 1. 原始 rag_retriever.invoke() ===")
raw_docs = vectorstore.as_retriever(search_kwargs={"k": 20}).invoke(QUERY)
print(f"原始返回文档数量: {len(raw_docs)}")

# 打印前3条的 metadata（关键！看 user_id 类型）
for i, doc in enumerate(raw_docs[:3]):
    meta = doc.metadata
    print(f"  [{i}] user_id={meta.get('user_id')} (类型:{type(meta.get('user_id'))}) | "
          f"is_deleted={meta.get('is_deleted')} | score≈{meta.get('score')}")

# ====================== 2. 用户过滤后 ======================
print("\n=== 2. 用户过滤后（user_id + is_deleted）===")
user_docs = [
    doc for doc in raw_docs
    if str(doc.metadata.get("user_id")) == str(TEST_USER_ID)
    and doc.metadata.get("is_deleted") == 0
]
print(f"过滤后剩余文档: {len(user_docs)}")

if user_docs:
    print("过滤后前2条标题示例:")
    for doc in user_docs[:2]:
        print(f"   • {doc.metadata.get('title')} (id={doc.metadata.get('id')})")
else:
    print("❌ 过滤后为空！← 这就是返回空笔记的罪魁祸首")

# ====================== 3. FlashRank 重排序后 ======================
print("\n=== 3. rerank_docs 重排序后 ===")
reranked = rerank_docs(QUERY, user_docs, top_n=8)
print(f"重排序后剩余: {len(reranked)}")

# ====================== 4. 完整工具调用（semantic_search_notes） ======================
print("\n=== 4. semantic_search_notes 完整调用 ===")
search_result = tools_by_name["semantic_search_notes"].invoke({"query": QUERY, "limit": 8})
print(json.dumps(json.loads(search_result), indent=2, ensure_ascii=False))

# ====================== 5. 完整工具调用（cross_note_analysis） ======================
print("\n=== 5. cross_note_analysis 完整调用 ===")
cross_result = tools_by_name["cross_note_analysis"].invoke({"analysis_query": QUERY, "limit": 8})
print(json.dumps(json.loads(cross_result), indent=2, ensure_ascii=False))

print("\n✅ 诊断完成！请把**全部输出**复制给我，我立刻告诉你具体是哪一步出了问题，并给出最终修复代码。")