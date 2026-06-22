"""
app/worker.py

Celery 应用工厂。使用已有的 Redis 作为 broker（DB 1）和 result backend（DB 1），
不引入任何新的基础设施。

启动 worker：
  celery -A app.worker worker --loglevel=info
监控（可选）：
  celery -A app.worker flower
"""

from celery import Celery
from app.config import settings

_broker_url  = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/1"
_backend_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/1"

celery_app = Celery(
    "black_note",
    broker=_broker_url,
    backend=_backend_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    # 消费后再 ACK：worker 崩溃时任务自动重新入队，不丢失
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
)
