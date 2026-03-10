import os
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer
from typing import List


class BGEEmbeddings(Embeddings):
    """
    本地bge-m3模型封装
    - 不依赖任何云端API，数据不出本地
    - 支持中英文多语言，最长8192 token
    - 继承LangChain Embeddings基类，可无缝接入所有LangChain组件
    """
    _instance = None  # 单例，避免重复加载2GB模型

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            print("⏳ 加载 bge-m3 模型\...")
            cls._instance.model = SentenceTransformer(
                "BAAI/bge-m3", device="cpu"
            )
            print("✅ bge-m3 加载成功")
        return cls._instance

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        batch_size = 4
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            all_embeddings.extend(
                self.model.encode(
                    batch,
                    normalize_embeddings=True,
                    show_progress_bar=False
                ).tolist()
            )
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(
            text, normalize_embeddings=True
        ).tolist()