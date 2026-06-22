"""
app/database.py

MongoDB 连接初始化（Motor + Beanie）。
在应用启动 lifespan 中调用 init_db()，之后所有 Document 操作直接调用，
无需显式传递 session。
"""

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.config import settings

_client: AsyncIOMotorClient | None = None


def get_motor_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URL)
    return _client


async def init_db() -> None:
    from app.models import User, Note, Follow, NoteLike, ChatSession
    await init_beanie(
        database=get_motor_client()[settings.MONGODB_DB],
        document_models=[User, Note, Follow, NoteLike, ChatSession],
    )
