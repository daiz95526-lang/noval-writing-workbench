from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from threading import RLock

from app.models.schemas import (
    LongTask,
    LongTaskStatus,
    TaskError,
    TaskType,
)
from app.services.project_context import get_current_project_id


class TaskCancelled(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_message(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    message = re.sub(
        r"(?i)(api[_ -]?key|authorization|bearer)(\s*[:=]\s*|\s+)[^\s,;]+",
        r"\1: [REDACTED]",
        message,
    )
    return message[:1000]


def classify_error(exc: Exception) -> TaskError:
    error_type = type(exc).__name__
    message = _safe_message(exc)
    lowered = f"{error_type} {message}".lower()
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return TaskError(
        type=error_type,
        message=message,
        http_status=status if isinstance(status, int) else None,
        is_timeout=(
            isinstance(exc, TimeoutError)
            or "timeout" in lowered
            or "timed out" in lowered
            or "超时" in lowered
        ),
        is_api_key_error=(
            status in {401, 403}
            or "api key" in lowered
            or "authentication" in lowered
            or "unauthorized" in lowered
            or "未配置 api key" in lowered
        ),
        is_json_parse_error=(
            "json" in lowered
            and ("parse" in lowered or "decode" in lowered or "解析" in lowered)
        ),
    )


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, LongTask] = {}
        self._lock = RLock()

    def create(
        self,
        task_type: TaskType,
        input_summary: dict | None = None,
        *,
        project_id: str | None = None,
        operation_type: str = "",
        target_id: str = "",
        user_visible_title: str = "",
    ) -> LongTask:
        task = LongTask(
            task_id=uuid.uuid4().hex[:12],
            type=task_type,
            project_id=project_id or get_current_project_id(),
            operation_type=operation_type or task_type.value,
            target_id=target_id,
            user_visible_title=user_visible_title or task_type.value,
            input_summary=input_summary or {},
        )
        with self._lock:
            self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str, project_id: str | None = None) -> LongTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and project_id and task.project_id != project_id:
                return None
            return task

    def list(
        self,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[LongTask]:
        with self._lock:
            tasks = sorted(
                (
                    task
                    for task in self._tasks.values()
                    if project_id is None or task.project_id == project_id
                ),
                key=lambda task: task.created_at,
                reverse=True,
            )
            return tasks[: max(1, min(limit, 200))]

    def clear(self, project_id: str | None = None) -> None:
        with self._lock:
            if project_id is None:
                self._tasks.clear()
                return
            self._tasks = {
                task_id: task
                for task_id, task in self._tasks.items()
                if task.project_id != project_id
            }

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
            task = self._require(task_id)
            if task.status == LongTaskStatus.CANCELLED:
                raise TaskCancelled("任务已取消")
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
            return task

    def succeed(self, task_id: str, result: dict, message: str) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if task.status == LongTaskStatus.CANCELLED:
                raise TaskCancelled("任务已取消")
            now = _now()
            task.status = LongTaskStatus.SUCCESS
            task.progress = 100.0
            task.stage = "已完成"
            task.message = message
            task.result = result
            task.error = None
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} {message}")
            task.logs = task.logs[-50:]
            return task

    def partial_succeed(self, task_id: str, result: dict, message: str) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if task.status == LongTaskStatus.CANCELLED:
                raise TaskCancelled("任务已取消")
            now = _now()
            task.status = LongTaskStatus.PARTIAL_SUCCESS
            task.progress = 100.0
            task.stage = "已生成，但有提醒"
            task.message = message
            task.result = result
            task.error = None
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} {message}")
            task.logs = task.logs[-50:]
            return task

    def fail(
        self,
        task_id: str,
        exc: Exception,
        result: dict | None = None,
    ) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if task.status == LongTaskStatus.CANCELLED:
                return task
            now = _now()
            error = classify_error(exc)
            if error.is_timeout:
                error.message = "模型请求超时，请检查网络/API 服务或稍后重试"
            task.status = LongTaskStatus.FAILED
            task.stage = "已失败"
            task.message = error.message
            task.error = error
            if result is not None:
                task.result = result
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} 失败: {task.message}")
            task.logs = task.logs[-50:]
            return task

    def cancel(self, task_id: str, project_id: str | None = None) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            if project_id and task.project_id != project_id:
                raise KeyError(task_id)
            if task.status in {
                LongTaskStatus.SUCCESS,
                LongTaskStatus.PARTIAL_SUCCESS,
                LongTaskStatus.FAILED,
                LongTaskStatus.CANCELLED,
            }:
                return task
            now = _now()
            task.status = LongTaskStatus.CANCELLED
            task.stage = "已取消"
            task.message = "用户已请求取消任务"
            task.updated_at = now
            task.finished_at = now
            task.logs.append(f"{now.isoformat()} 用户请求取消")
            task.logs = task.logs[-50:]
            return task

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
            task = self._require(task_id)
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
            return task

    def merge_result(self, task_id: str, values: dict) -> LongTask:
        with self._lock:
            task = self._require(task_id)
            task.result.update(values)
            task.updated_at = _now()
            return task

    def _require(self, task_id: str) -> LongTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task


task_manager = TaskManager()
