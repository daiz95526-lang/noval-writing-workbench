from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import settings
from app.logging_config import redact
from app.models.schemas import LongTask, LongTaskStatus, TaskError, TaskType
from app.services.file_ops import (
    atomic_write_json,
    read_json_with_recovery,
    safe_child,
    soft_delete,
)
from app.services.project_context import get_current_project_id

logger = logging.getLogger("noval.tasks")

class TaskCancelled(RuntimeError):
    pass


_TERMINAL_STATUSES = {
    LongTaskStatus.SUCCESS,
    LongTaskStatus.PARTIAL_SUCCESS,
    LongTaskStatus.FAILED,
    LongTaskStatus.CANCELLED,
    LongTaskStatus.INTERRUPTED,
}
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_message(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    return redact(message)[:1000]


def classify_error(exc: Exception) -> TaskError:
    error_type = type(exc).__name__
    message = _safe_message(exc)
    lowered = f"{error_type} {message}".lower()
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    is_timeout = (
        isinstance(exc, TimeoutError)
        or "timeout" in lowered
        or "timed out" in lowered
        or "超时" in lowered
    )
    is_api_key_error = (
        status in {401, 403}
        or "api key" in lowered
        or "authentication" in lowered
        or "unauthorized" in lowered
        or "未配置 api key" in lowered
    )
    if is_timeout:
        error_code = "MODEL_TIMEOUT"
    elif is_api_key_error:
        error_code = "MODEL_AUTH_ERROR"
    elif "json" in lowered and ("parse" in lowered or "decode" in lowered or "解析" in lowered):
        error_code = "MODEL_RESPONSE_INVALID"
    else:
        error_code = "TASK_FAILED"
    return TaskError(
        type=error_type,
        message=message,
        error_code=error_code,
        http_status=status if isinstance(status, int) else None,
        is_timeout=is_timeout,
        is_api_key_error=is_api_key_error,
        is_json_parse_error=error_code == "MODEL_RESPONSE_INVALID",
        retryable=is_timeout or status in {408, 409, 425, 429, 500, 502, 503, 504},
    )


class TaskManager:
    def __init__(self, storage_root: Path | None = None) -> None:
        self._tasks: dict[str, LongTask] = {}
        self._retry_payloads: dict[str, dict[str, Any]] = {}
        self._loaded_projects: set[str] = set()
        self._storage_root = Path(storage_root or settings.task_storage_dir)
        self._lock = RLock()

    @property
    def storage_root(self) -> Path:
        return self._storage_root

    def set_storage_root(self, root: Path) -> None:
        with self._lock:
            self._tasks.clear()
            self._retry_payloads.clear()
            self._loaded_projects.clear()
            self._storage_root = Path(root)

    def create(
        self,
        task_type: TaskType,
        input_summary: dict | None = None,
        *,
        project_id: str | None = None,
        operation_type: str = "",
        target_id: str = "",
        user_visible_title: str = "",
        retry_payload: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        retry_of: str = "",
        attempt: int = 1,
    ) -> LongTask:
        selected_project = project_id or get_current_project_id()
        timeout = timeout_seconds or settings.task_timeout_seconds
        now = _now()
        task = LongTask(
            task_id=uuid.uuid4().hex[:12],
            type=task_type,
            project_id=selected_project,
            operation_type=operation_type or task_type.value,
            target_id=target_id,
            user_visible_title=user_visible_title or task_type.value,
            input_summary=input_summary or {},
            timeout_seconds=timeout,
            deadline_at=now + timedelta(seconds=timeout),
            retry_of=retry_of,
            attempt=max(1, attempt),
            retry_available=bool(retry_payload),
        )
        with self._lock:
            self._load_project(selected_project)
            self._tasks[task.task_id] = task
            if retry_payload:
                self._retry_payloads[task.task_id] = retry_payload
            self._persist_project(selected_project)
            self._emit(task, "task_created")
        return task

    def get(self, task_id: str, project_id: str | None = None) -> LongTask | None:
        with self._lock:
            if project_id:
                self._load_project(project_id)
                self._expire_project(project_id)
            task = self._tasks.get(task_id)
            if task is not None and project_id and task.project_id != project_id:
                return None
            return task

    def list(
        self,
        limit: int = 50,
        project_id: str | None = None,
        *,
        offset: int = 0,
        status: LongTaskStatus | None = None,
    ) -> list[LongTask]:
        with self._lock:
            if project_id:
                self._load_project(project_id)
                self._expire_project(project_id)
            tasks = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if project_id is None or task.project_id == project_id
                    if status is None or task.status == status
                ),
                key=lambda task: task.created_at,
                reverse=True,
            )
            safe_offset = max(0, offset)
            safe_limit = max(1, min(limit, 200))
            return tasks[safe_offset : safe_offset + safe_limit]

    def clear(self, project_id: str | None = None) -> None:
        with self._lock:
            if project_id is None:
                self._tasks.clear()
                self._retry_payloads.clear()
                self._loaded_projects.clear()
                return
            task_ids = {
                task_id
                for task_id, task in self._tasks.items()
                if task.project_id == project_id
            }
            for task_id in task_ids:
                self._tasks.pop(task_id, None)
                self._retry_payloads.pop(task_id, None)
            self._loaded_projects.discard(project_id)

    def archive_project(self, project_id: str) -> Path | None:
        with self._lock:
            project_root = safe_child(self._storage_root, project_id)
            archived = None
            if project_root.exists():
                archived = soft_delete(
                    project_root,
                    safe_child(self._storage_root, ".trash"),
                )
            self.clear(project_id)
            return archived

    def update(
        self,
        task_id: str,
        *,
        status: LongTaskStatus | None = None,
        progress: float | None = None,
        stage: str | None = None,
        message: str | None = None,
        log: str | None = None,
    ) -> LongTask:
        with self._lock:
            task = self._require_mutable(task_id)
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = max(0.0, min(float(progress), 100.0))
            if stage is not None:
                task.stage = stage
            if message is not None:
                task.message = message
            now = _now()
            task.updated_at = now
            if task.status == LongTaskStatus.RUNNING and task.started_at is None:
                task.started_at = now
            if log:
                task.logs.append(f"{now.isoformat()} {log}")
                task.logs = task.logs[-50:]
            self._persist_project(task.project_id)
            self._emit(task, "task_progress")
            return task

    def succeed(self, task_id: str, result: dict, message: str) -> LongTask:
        return self._finish(task_id, LongTaskStatus.SUCCESS, result, message, "已完成")

    def partial_succeed(self, task_id: str, result: dict, message: str) -> LongTask:
        return self._finish(
            task_id,
            LongTaskStatus.PARTIAL_SUCCESS,
            result,
            message,
            "已生成，但有提醒",
        )

    def _finish(
        self,
        task_id: str,
        status: LongTaskStatus,
        result: dict,
        message: str,
        stage: str,
    ) -> LongTask:
        with self._lock:
            task = self._require_mutable(task_id)
            now = _now()
            task.status = status
            task.progress = 100.0
            task.stage = stage
            task.message = message
            task.result = result
            task.error = None
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} {message}")
            task.logs = task.logs[-50:]
            self._persist_project(task.project_id)
            self._emit(task, "task_finished")
            return task

    def fail(self, task_id: str, exc: Exception, result: dict | None = None) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if task.status in _TERMINAL_STATUSES:
                return task
            now = _now()
            error = classify_error(exc)
            if error.is_timeout:
                error.message = "模型请求超时，请检查网络/API 服务或稍后重试"
            task.status = LongTaskStatus.FAILED
            task.stage = "已失败"
            task.message = error.message
            task.error = error
            task.retry_available = bool(self._retry_payloads.get(task_id)) and error.retryable
            if result is not None:
                task.result = result
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} 失败: {task.message}")
            task.logs = task.logs[-50:]
            self._persist_project(task.project_id)
            self._emit(task, "task_failed", error_code=error.error_code)
            return task

    def cancel(self, task_id: str, project_id: str | None = None) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if project_id and task.project_id != project_id:
                raise KeyError(task_id)
            if task.status in _TERMINAL_STATUSES:
                return task
            now = _now()
            task.status = LongTaskStatus.CANCELLED
            task.stage = "已取消"
            task.message = "用户已请求取消任务"
            task.updated_at = now
            task.finished_at = now
            task.retry_available = bool(self._retry_payloads.get(task_id))
            task.logs.append(f"{now.isoformat()} 用户请求取消")
            task.logs = task.logs[-50:]
            self._persist_project(task.project_id)
            self._emit(task, "task_cancelled")
            return task

    def clone_for_retry(self, task_id: str, project_id: str) -> tuple[LongTask, dict[str, Any]]:
        with self._lock:
            self._load_project(project_id)
            original = self._require(task_id)
            if original.project_id != project_id:
                raise KeyError(task_id)
            if original.status not in {
                LongTaskStatus.FAILED,
                LongTaskStatus.INTERRUPTED,
                LongTaskStatus.CANCELLED,
            }:
                raise ValueError("只有失败、中断或已取消的任务可以重试")
            payload = self._retry_payloads.get(task_id)
            if not payload:
                raise ValueError("该历史任务没有可用的重试参数")
            clone = self.create(
                original.type,
                original.input_summary,
                project_id=project_id,
                operation_type=original.operation_type,
                target_id=original.target_id,
                user_visible_title=original.user_visible_title,
                retry_payload=payload,
                timeout_seconds=original.timeout_seconds,
                retry_of=original.task_id,
                attempt=original.attempt + 1,
            )
            return clone, dict(payload)

    def set_partial_generation(
        self,
        task_id: str,
        *,
        current_segment: int,
        total_segments: int,
        partial_text: str,
        draft_id: str = "",
        prompt_chars: int | None = None,
    ) -> LongTask:
        with self._lock:
            task = self._require_mutable(task_id)
            now = _now()
            task.current_segment = current_segment
            task.total_segments = total_segments
            task.partial_text = partial_text
            task.partial_word_count = len("".join(partial_text.split()))
            task.draft_id = draft_id
            task.can_accept = bool(partial_text.strip())
            task.result.update(
                {
                    "partial_text": partial_text,
                    "partial_word_count": task.partial_word_count,
                    "current_segment": current_segment,
                    "total_segments": total_segments,
                    "draft_id": draft_id,
                    "can_accept": task.can_accept,
                }
            )
            task.updated_at = now
            if prompt_chars is not None:
                task.logs.append(
                    f"{now.isoformat()} 第 {current_segment}/{total_segments} 段已保存，"
                    f"Prompt 字符数：{prompt_chars}，累计 {task.partial_word_count} 字"
                )
                task.logs = task.logs[-50:]
            self._persist_project(task.project_id)
            return task

    def merge_result(self, task_id: str, values: dict) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            task.result.update(values)
            task.updated_at = _now()
            self._persist_project(task.project_id)
            return task

    def _task_file(self, project_id: str) -> Path:
        if not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("project_id 格式不安全，无法保存任务")
        return safe_child(self._storage_root, project_id, "tasks.json")

    def _load_project(self, project_id: str) -> None:
        if project_id in self._loaded_projects:
            return
        path = self._task_file(project_id)
        payload = read_json_with_recovery(
            path,
            default={"schema_version": 1, "tasks": []},
        )
        records = payload.get("tasks", []) if isinstance(payload, dict) else []
        changed = False
        for record in records:
            if not isinstance(record, dict):
                continue
            task_payload = record.get("task", record)
            try:
                task = LongTask.model_validate(task_payload)
            except ValueError:
                continue
            if task.project_id != project_id:
                continue
            retry_payload = record.get("retry_payload")
            if isinstance(retry_payload, dict) and retry_payload:
                self._retry_payloads[task.task_id] = retry_payload
                task.retry_available = task.status in {
                    LongTaskStatus.FAILED,
                    LongTaskStatus.CANCELLED,
                    LongTaskStatus.INTERRUPTED,
                }
            if task.status in {LongTaskStatus.PENDING, LongTaskStatus.RUNNING}:
                now = _now()
                task.status = LongTaskStatus.INTERRUPTED
                task.stage = "应用重启，任务已中断"
                task.message = "应用重启时任务尚未完成，可从任务详情重试"
                task.error = TaskError(
                    type="InterruptedError",
                    message=task.message,
                    error_code="TASK_INTERRUPTED",
                    retryable=True,
                )
                task.updated_at = now
                task.finished_at = now
                task.retry_available = bool(retry_payload)
                changed = True
                self._emit(task, "task_interrupted", error_code="TASK_INTERRUPTED")
            self._tasks[task.task_id] = task
        self._loaded_projects.add(project_id)
        if changed:
            self._persist_project(project_id)

    def _expire_project(self, project_id: str) -> None:
        now = _now()
        changed = False
        for task in self._tasks.values():
            if (
                task.project_id == project_id
                and task.status in {LongTaskStatus.PENDING, LongTaskStatus.RUNNING}
                and task.deadline_at
                and now >= task.deadline_at
            ):
                task.status = LongTaskStatus.FAILED
                task.stage = "已超时"
                task.message = "任务超过允许执行时间，已停止等待，可重试"
                task.error = TaskError(
                    type="TimeoutError",
                    message=task.message,
                    error_code="TASK_TIMEOUT",
                    is_timeout=True,
                    retryable=True,
                )
                task.updated_at = now
                task.finished_at = now
                task.retry_available = bool(self._retry_payloads.get(task.task_id))
                changed = True
                self._emit(task, "task_timed_out", error_code="TASK_TIMEOUT")
        if changed:
            self._persist_project(project_id)

    def _persist_project(self, project_id: str) -> None:
        records = [
            {
                "task": task.model_dump(mode="json"),
                "retry_payload": self._retry_payloads.get(task.task_id, {}),
            }
            for task in sorted(
                (
                    task
                    for task in self._tasks.values()
                    if task.project_id == project_id
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )[: settings.task_history_limit]
        ]
        atomic_write_json(
            self._task_file(project_id),
            {"schema_version": 1, "tasks": records},
            max_backups=3,
        )

    def _require(self, task_id: str) -> LongTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _require_mutable(self, task_id: str) -> LongTask:
        task = self._require(task_id)
        if task.status in _TERMINAL_STATUSES:
            raise TaskCancelled(f"任务已结束: {task.status.value}")
        if task.deadline_at and _now() >= task.deadline_at:
            self._expire_project(task.project_id)
            raise TaskCancelled("任务已超时")
        return task

    @staticmethod
    def _emit(task: LongTask, event: str, *, error_code: str = "") -> None:
        duration_ms = None
        if task.started_at:
            end = task.finished_at or _now()
            duration_ms = round((end - task.started_at).total_seconds() * 1000, 2)
        logger.info(
            event,
            extra={
                "task_id": task.task_id,
                "project_id": task.project_id,
                "operation": task.operation_type,
                "stage": task.stage,
                "duration_ms": duration_ms,
                "error_code": error_code,
            },
        )


task_manager = TaskManager()
