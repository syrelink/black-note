import os
from typing import List

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")


class BGEEmbeddings(Embeddings):
    """本地 bge-m3 embedding，单例避免重复加载大模型。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            print("⏳ 加载 bge-m3 模型）...")
            cls._instance.model = SentenceTransformer("BAAI/bge-m3", device="cpu")
            print("✅ bge-m3 加载成功")
        return cls._instance

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        batch_size = 4
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_embeddings.extend(
                self.model.encode(
                    batch,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ).tolist()
            )
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

