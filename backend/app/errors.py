from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logging_config import get_request_id, redact


logger = logging.getLogger("noval.errors")


class AppError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": redact(message),
            "details": details or {},
            "request_id": get_request_id(),
            "retryable": retryable,
        },
    )


def _http_error_code(status_code: int, message: str) -> tuple[str, bool]:
    lowered = message.lower()
    if "api key" in lowered or "authentication" in lowered or "unauthorized" in lowered:
        return "MODEL_AUTH_ERROR", status_code >= 500
    mapping = {
        400: ("BAD_REQUEST", False),
        401: ("UNAUTHORIZED", False),
        403: ("FORBIDDEN", False),
        404: ("NOT_FOUND", False),
        408: ("REQUEST_TIMEOUT", True),
        409: ("CONFLICT", False),
        413: ("UPLOAD_TOO_LARGE", False),
        415: ("UNSUPPORTED_MEDIA_TYPE", False),
        422: ("VALIDATION_ERROR", False),
        429: ("RATE_LIMITED", True),
        500: ("INTERNAL_ERROR", True),
        502: ("MODEL_UPSTREAM_ERROR", True),
        503: ("SERVICE_UNAVAILABLE", True),
        504: ("MODEL_TIMEOUT", True),
    }
    return mapping.get(
        status_code,
        ("HTTP_ERROR", status_code >= 500),
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "application_error",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        },
    )
    return error_response(
        exc.status_code,
        exc.error_code,
        exc.message,
        details=exc.details,
        retryable=exc.retryable,
    )


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, str):
        message = exc.detail
        details: dict[str, Any] = {}
    else:
        message = "请求无法完成"
        details = {"reason": redact(exc.detail)}
    error_code, retryable = _http_error_code(exc.status_code, message)
    logger.warning(
        "http_error",
        extra={
            "error_code": error_code,
            "status_code": exc.status_code,
            "retryable": retryable,
        },
    )
    return error_response(
        exc.status_code,
        error_code,
        message,
        details=details,
        retryable=retryable,
    )


async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    issues = [
        {
            "location": [str(part) for part in error.get("loc", ())],
            "message": str(error.get("msg") or "字段无效"),
            "type": str(error.get("type") or "validation_error"),
        }
        for error in exc.errors()
    ]
    logger.warning(
        "validation_error",
        extra={"error_code": "VALIDATION_ERROR", "status_code": 422},
    )
    return error_response(
        422,
        "VALIDATION_ERROR",
        "请求参数不符合要求，请检查输入后重试",
        details={"issues": issues},
    )


async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={
            "error_code": "INTERNAL_ERROR",
            "status_code": 500,
            "retryable": True,
        },
    )
    return error_response(
        500,
        "INTERNAL_ERROR",
        "后端处理请求时发生错误，请稍后重试；问题持续时可在诊断日志中按 request_id 查找",
        retryable=True,
    )
