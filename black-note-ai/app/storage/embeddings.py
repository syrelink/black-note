import os
from typing import List

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")


# ==================== 全局单例（只加载一次） ====================
_model = None

def _get_model():
    global _model
    if _model is None:
        print("⏳ 首次加载 bge-m3 模型（只需加载一次）...")
        _model = SentenceTransformer("BAAI/bge-m3", device="cpu")
        print("✅ bge-m3 加载成功")
    return _model

# ==================== 对外使用的 LangChain 接口类 ====================
class BGEEmbeddings(Embeddings):

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = _get_model()  # ← 每次都调用同一个模型
        batch_size = 4
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            all_embeddings.extend(
                model.encode(batch, normalize_embeddings=True, show_progress_bar=False).tolist()
            )
        return all_embeddings

    # 把用户当前输入的问题转成向量（用于检索时匹配）
    def embed_query(self, text: str) -> List[float]:
        model = _get_model()  # ← 每次都调用同一个模型
        return model.encode(text, normalize_embeddings=True).tolist()