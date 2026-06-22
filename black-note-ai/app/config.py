"""
app/config.py

统一配置管理，通过 .env 文件或环境变量注入。
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ── MongoDB ────────────────────────────────────────────────────
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DB:  str = os.getenv("MONGODB_DB",  "black_note")

    # ── Qdrant ─────────────────────────────────────────────────────
    QDRANT_URL:        str = os.getenv("QDRANT_URL",        "http://localhost:6333")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "black_note_all")
    QDRANT_VECTOR_SIZE: int = 1024   # BGE-M3 输出维度

    # ── Redis ──────────────────────────────────────────────────────
    REDIS_HOST:     str = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT:     int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "") or ""

    # ── MinIO ──────────────────────────────────────────────────────
    MINIO_ENDPOINT:   str  = os.getenv("MINIO_ENDPOINT",   "localhost:9000")
    MINIO_ACCESS_KEY: str  = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str  = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    MINIO_BUCKET:     str  = os.getenv("MINIO_BUCKET",     "syr")
    MINIO_SECURE:     bool = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # ── Token ──────────────────────────────────────────────────────
    TOKEN_TTL_SECONDS: int = 60 * 60
    DEFAULT_AVATAR: str = (
        f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}"
        f"/{os.getenv('MINIO_BUCKET', 'syr')}/434661c680244262b6cc4301e633dcdc.jpeg"
    )

    # ── Redis key 前缀（与前端约定保持一致）──────────────────────────
    TOKEN_KEY_PREFIX:       str = "login:token:"
    NOTE_DETAIL_KEY:        str = "note:detail:"
    LIKE_SET_KEY:           str = "like:set:"
    LIKE_COUNT_KEY:         str = "like:count:"
    FOLLOW_KEY:             str = "follow:"
    FEED_INBOX_KEY:         str = "feed:inbox:"

    CACHE_TTL_MINUTES:      int = 30
    CACHE_NULL_TTL_MINUTES: int = 2


settings = Settings()
