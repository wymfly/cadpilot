"""统一错误处理：ErrorResponse 模型 + FastAPI 异常处理器。

所有 API 错误遵循格式：
    { "error": { "code": "ERROR_CODE", "message": "...", "details": ... } }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# 错误码常量
# ---------------------------------------------------------------------------

class ErrorCode:
    """标准错误码。"""

    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    INVALID_JOB_STATE = "INVALID_JOB_STATE"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_INPUT_TYPE = "INVALID_INPUT_TYPE"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    PROFILE_EXISTS = "PROFILE_EXISTS"
    PROFILE_PROTECTED = "PROFILE_PROTECTED"
    REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
    TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
    TEMPLATE_EXISTS = "TEMPLATE_EXISTS"


# ---------------------------------------------------------------------------
# 错误响应模型
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """统一错误体。"""

    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    """统一错误响应包装。"""

    error: ErrorDetail


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class APIError(Exception):
    """可直接映射为 HTTP 响应的业务异常。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class JobNotFoundError(APIError):
    """Job 不存在。"""

    def __init__(self, job_id: str) -> None:
        super().__init__(
            status_code=404,
            code=ErrorCode.JOB_NOT_FOUND,
            message=f"Job {job_id} not found",
        )


class InvalidJobStateError(APIError):
    """Job 状态不允许当前操作。"""

    def __init__(self, job_id: str, current: str, expected: str) -> None:
        super().__init__(
            status_code=409,
            code=ErrorCode.INVALID_JOB_STATE,
            message=(
                f"Job {job_id} is in state '{current}', expected '{expected}'"
            ),
        )


# ---------------------------------------------------------------------------
# 异常处理器注册
# ---------------------------------------------------------------------------


def _build_error_response(
    status_code: int, code: str, message: str, details: Any = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
    )


def register_error_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上注册统一异常处理器。"""

    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return _build_error_response(
            exc.status_code, exc.code, exc.message, exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        return _build_error_response(
            422,
            ErrorCode.VALIDATION_FAILED,
            "请求参数校验失败",
            details=exc.errors(),
        )
