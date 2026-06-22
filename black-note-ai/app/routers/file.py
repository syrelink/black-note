"""
app/routers/file.py  →  /file/*

对应 Java FileController，URL 路径完全一致。
"""

from fastapi import APIRouter, Depends, UploadFile

from app.auth import get_request_user_id
from app.common import Result
from app.services import file_service

router = APIRouter(prefix="/file", tags=["文件"])


@router.post("/upload")
async def upload_image(
    file: UploadFile,
    _: str = Depends(get_request_user_id),
) -> Result[str]:
    url = await file_service.upload_image(file)
    return Result.success(url)
