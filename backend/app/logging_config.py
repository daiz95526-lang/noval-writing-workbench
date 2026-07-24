from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import settings


request_id_var: ContextVar[str] = ContextVar("request_id", default="")
project_id_var: ContextVar[str] = ContextVar("project_id", default="")
task_id_var: ContextVar[str] = ContextVar("task_id", default="")
operation_var: ContextVar[str] = ContextVar("operation", default="")
stage_var: ContextVar[str] = ContextVar("stage", default="")

_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|authorization|token)(\s*[:=]\s*)[^\s,;]+"
)
_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:\\|/home/|/users/)[^\s\"']+")


def redact(value: Any) -> str:
    text = str(value)
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _SECRET_PATTERN.sub(r"\1: [REDACTED]", text)
    if not settings.log_include_paths:
        text = _PATH_PATTERN.sub("[LOCAL_PATH]", text)
    return text[:4000]


def get_request_id() -> str:
    return request_id_var.get()


@contextmanager
def log_context(
    *,
    request_id: str | None = None,
    project_id: str | None = None,
    task_id: str | None = None,
    operation: str | None = None,
    stage: str | None = None,
):
    values = (
        (request_id_var, request_id),
        (project_id_var, project_id),
        (task_id_var, task_id),
        (operation_var, operation),
        (stage_var, stage),
    )
    tokens = [(variable, variable.set(value)) for variable, value in values if value is not None]
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", "") or request_id_var.get(),
            "task_id": getattr(record, "task_id", "") or task_id_var.get(),
            "project_id": getattr(record, "project_id", "") or project_id_var.get(),
            "operation": getattr(record, "operation", "") or operation_var.get(),
            "stage": getattr(record, "stage", "") or stage_var.get(),
        }
        for name in ("duration_ms", "error_code", "status_code", "retryable"):
            value = getattr(record, name, None)
            if value not in (None, ""):
                payload[name] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
            payload["exception_message"] = redact(record.exc_info[1])
            if settings.log_include_paths:
                payload["traceback"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger("noval")
    if getattr(root, "_noval_configured", False):
        return
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    file_handler = RotatingFileHandler(
        settings.log_dir / "noval.jsonl",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.setLevel(getattr(logging, settings.log_level, logging.INFO))
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.propagate = False
    setattr(root, "_noval_configured", True)
