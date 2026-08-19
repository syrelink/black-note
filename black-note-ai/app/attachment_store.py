"""MinIO-backed binary attachment storage.

PostgreSQL keeps ownership and metadata; this module keeps large immutable bytes out of
the relational database and exposes a small async interface to the Agent Harness.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Protocol

from minio import Minio


class AttachmentObjectStore(Protocol):
    async def setup(self) -> None: ...
    async def put(self, object_key: str, content: bytes, mime_type: str) -> None: ...
    async def get(self, object_key: str) -> bytes: ...
    async def delete_many(self, object_keys: list[str]) -> None: ...


class MinioAttachmentStore:
    """通过 MinIO S3 API 保存图片原文；所有阻塞 SDK 调用都移出事件循环。"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ):
        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    @classmethod
    def from_env(cls) -> "MinioAttachmentStore":
        secure = os.getenv("MINIO_SECURE", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        return cls(
            endpoint=os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            bucket=os.getenv("MINIO_BUCKET", "game-rover-attachments"),
            secure=secure,
        )

    async def setup(self) -> None:
        def ensure_bucket() -> None:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)

        await asyncio.to_thread(ensure_bucket)

    async def put(self, object_key: str, content: bytes, mime_type: str) -> None:
        await asyncio.to_thread(
            self.client.put_object,
            self.bucket,
            object_key,
            io.BytesIO(content),
            len(content),
            content_type=mime_type,
        )

    async def get(self, object_key: str) -> bytes:
        def download() -> bytes:
            response = self.client.get_object(self.bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(download)

    async def delete_many(self, object_keys: list[str]) -> None:
        for object_key in object_keys:
            await asyncio.to_thread(self.client.remove_object, self.bucket, object_key)
