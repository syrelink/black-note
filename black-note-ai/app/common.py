"""
app/common.py

统一响应体 Result[T]，与 Java 端 com.syr.dto.Result 格式完全一致：
  {"code": 200, "message": "OK", "data": ...}

BusinessException 用于业务层抛出带 HTTP 状态码的错误。
全局异常处理器注册在 main.py 中。
"""

from typing import Any, Generic, TypeVar
from fastapi import HTTPException
from pydantic import BaseModel

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    code: int
    message: str
    data: T | None = None

    @classmethod
    def success(cls, data: Any = None) -> "Result":
        return cls(code=200, message="OK", data=data)

    @classmethod
    def fail(cls, code: int = 500, message: str = "内部错误") -> "Result":
        return cls(code=code, message=message, data=None)


class BusinessException(HTTPException):
    """业务异常，抛出后由全局处理器转为 Result 格式返回。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)
