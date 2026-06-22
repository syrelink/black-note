"""
app/tasks.py

Celery 任务定义。

只有向量同步被异步化——它是唯一耗时操作（Embedding 推理 1~10s）。
其余操作（点赞落库、缓存删除、Feed 推送）在请求内同步完成。

Celery worker 是普通线程，不在 event loop 中，通过 asyncio.run() 运行 async 函数。
"""

import asyncio
import logging

from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.vector_sync",
    max_retries=3,
    default_retry_delay=30,
)
def vector_sync(self, note_id: str, action: str = "sync") -> None:
    """
    同步笔记内容到 Qdrant 向量库。

    action="sync"   → 新建或更新
    action="delete" → 从向量库删除
    """
    from app.storage.sync import delete_note_from_vectorstore, sync_single_note

    try:
        if action == "delete":
            asyncio.run(delete_note_from_vectorstore(note_id))
        else:
            asyncio.run(sync_single_note(note_id))
        logger.info("向量同步完成 note_id=%s action=%s", note_id, action)
    except Exception as exc:
        logger.error("向量同步失败 note_id=%s action=%s: %s", note_id, action, exc)
        raise self.retry(exc=exc)
