"""
app/routers/feed.py  →  /feed

对应 Java FeedController，URL 路径完全一致。
"""

from fastapi import APIRouter, Depends

from app.auth import get_request_user_id
from app.common import Result
from app.schemas.feed import FeedResponse
from app.services import feed_service

router = APIRouter(prefix="/feed", tags=["Feed 流"])


@router.get("")
async def get_feed(
    last_timestamp: int = 0,
    page_size: int = 10,
    current_user_id: str = Depends(get_request_user_id),
) -> Result[FeedResponse]:
    vo = await feed_service.get_feed(current_user_id, last_timestamp, page_size)
    return Result.success(vo)
