"""
app/services/file_service.py

图片上传到 MinIO，返回可访问的公开 URL。
使用同步 minio SDK（I/O 在线程池中执行，对 FastAPI 友好）。
"""

import uuid
import logging
from io import BytesIO

from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error

from app.common import BusinessException
from app.config import settings

logger = logging.getLogger(__name__)

_minio: Minio | None = None


def _get_client() -> Minio:
    global _minio
    if _minio is None:
        _minio = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _minio


async def upload_image(file: UploadFile) -> str:
    if not file or not file.filename:
        raise BusinessException(400, "文件不能为空")

    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise BusinessException(400, "只能上传图片文件")

    suffix = ""
    if "." in file.filename:
        suffix = file.filename[file.filename.rfind("."):]
    object_name = uuid.uuid4().hex + (suffix or ".jpg")

    data = await file.read()
    try:
        client = _get_client()
        client.put_object(
            bucket_name=settings.MINIO_BUCKET,
            object_name=object_name,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as e:
        logger.error("MinIO 上传失败: %s", e)
        raise BusinessException(500, "图片上传失败，请重试")

    url = f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET}/{object_name}"
    logger.info("图片上传成功 url=%s", url)
    return url
