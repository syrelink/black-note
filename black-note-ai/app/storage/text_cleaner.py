"""
文本清理与 chunk 预处理模块（独立维护）
负责：Markdown 结构化分块 + 针对性清理 + 短块合并
"""

import re
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


def clean_text(text: str) -> str:
    """基础 Markdown 友好清理（Step 2 前置）"""
    if not text:
        return ""

    text = "".join(c for c in text if c.isprintable())
    text = re.sub(r"\s+", " ", text.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 删除常见垃圾
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)  # 分隔线
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)                        # 图片链接

    if not re.search(r'[\w\u4e00-\u9fff]', text):
        return ""

    return text.strip()


def preprocess_and_chunk(raw_text: str, metadata: dict) -> List[Document]:
    """
    【Step 2: Split】完整预处理 + 分块入口（核心函数）

    流程：
    1. clean_text（基础清理）
    2. MarkdownHeaderTextSplitter（按标题结构切）
    3. RecursiveCharacterTextSplitter（长度控制）
    4. 二次过滤 + 短块合并
    """
    if not raw_text:
        return []

    # 1. 基础清理
    cleaned = clean_text(raw_text)
    if not cleaned:
        return []

    # 2. Stage 1：结构化分块（保留标题层级）
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "Header 1"), ("##", "Header 2"),
            ("###", "Header 3"), ("####", "Header 4"),
        ],
        strip_headers=False
    )

    # 3. Stage 2：长度控制分块
    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=150,
        length_function=len,
        separators=["\n\n", "\n", ". ", "！", "。", " ", ""],
    )

    docs = header_splitter.split_text(cleaned)
    docs = recursive_splitter.split_documents(docs)

    # 4. 最终过滤 + 清理
    final_chunks = []
    for doc in docs:
        content = doc.page_content.strip()

        # 删除图片链接和纯分隔线
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'^\s*[-*_]{3,}\s*$', '', content, flags=re.MULTILINE)

        # 过滤无效 chunk
        if len(content) >= 50 and re.search(r'[\w\u4e00-\u9fff]', content):
            chunk_metadata = metadata.copy()
            chunk_metadata["original_content"] = raw_text  # ★ 存整篇原文供 LLM 使用

            final_chunks.append(Document(
                page_content=content,       # 清洗版 → 用于 embedding 检索
                metadata=chunk_metadata,
            ))

    print(f"[Cleaner] 本次笔记处理完成 → 生成 {len(final_chunks)} 个有效 chunk")
    return final_chunks