from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.logging_config import JsonFormatter, redact
from app.models.schemas import LongTaskStatus, TaskType
from app.services.file_ops import (
    atomic_write_json,
    atomic_write_text,
    list_backups,
    read_json_with_recovery,
    safe_child,
)
from app.services.model_policy import get_model_policy
from app.services.task_manager import TaskManager


def test_tasks_persist_partial_results_and_interrupt_running_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tasks"
    manager = TaskManager(root)
    task = manager.create(
        TaskType.GENERATION,
        {"chapter": "chapter-1"},
        project_id="project_a",
        retry_payload={"start_chapter_id": "chapter-1"},
    )
    manager.update(
        task.task_id,
        status=LongTaskStatus.RUNNING,
        progress=40,
        stage="生成第 2 段",
    )
    manager.set_partial_generation(
        task.task_id,
        current_segment=1,
        total_segments=3,
        partial_text="原创测试片段",
    )

    restarted = TaskManager(root)
    recovered = restarted.get(task.task_id, project_id="project_a")
    assert recovered is not None
    assert recovered.status == LongTaskStatus.INTERRUPTED
    assert recovered.partial_text == "原创测试片段"
    assert recovered.error is not None
    assert recovered.error.error_code == "TASK_INTERRUPTED"
    assert recovered.retry_available is True
    assert restarted.list(project_id="project_b") == []

    retried, payload = restarted.clone_for_retry(task.task_id, "project_a")
    assert retried.retry_of == task.task_id
    assert retried.attempt == 2
    assert payload == {"start_chapter_id": "chapter-1"}


def test_expired_task_becomes_failed_instead_of_loading_forever(tmp_path: Path) -> None:
    manager = TaskManager(tmp_path / "tasks")
    task = manager.create(
        TaskType.KNOWLEDGE_BUILD,
        project_id="project_a",
        retry_payload={"summary_only": False},
    )
    task.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    manager._persist_project("project_a")

    loaded = manager.get(task.task_id, project_id="project_a")
    assert loaded is not None
    assert loaded.status == LongTaskStatus.FAILED
    assert loaded.error is not None
    assert loaded.error.error_code == "TASK_TIMEOUT"
    assert loaded.finished_at is not None


def test_atomic_write_failure_preserves_original_and_cleans_temporary(
    tmp_path: Path,
) -> None:
    target = tmp_path / "project.json"
    atomic_write_text(target, "original")

    with patch("app.services.file_ops.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            atomic_write_text(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".*.tmp"))
    assert list_backups(target)


def test_corrupted_json_recovers_from_latest_valid_backup(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    atomic_write_json(target, {"version": 1})
    atomic_write_json(target, {"version": 2})
    target.write_text("{broken", encoding="utf-8")

    recovered = read_json_with_recovery(target)
    assert recovered == {"version": 1}
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}


def test_safe_child_rejects_absolute_and_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_child(tmp_path, "..", "escape.txt")
    with pytest.raises(ValueError):
        safe_child(tmp_path, str((tmp_path.parent / "escape.txt").resolve()))


def test_log_redaction_removes_keys_tokens_and_paths() -> None:
    message = (
        "Authorization: Bearer secret-token "
        "api_key=real-secret C:\\Users\\private\\novel.txt"
    )
    redacted = redact(message)
    assert "secret-token" not in redacted
    assert "real-secret" not in redacted
    assert "private\\novel" not in redacted
    assert "[REDACTED]" in redacted
    assert "[LOCAL_PATH]" in redacted

    record = logging.LogRecord(
        "noval.test",
        logging.ERROR,
        __file__,
        1,
        message,
        (),
        None,
    )
    rendered = JsonFormatter().format(record)
    assert "secret-token" not in rendered
    assert "real-secret" not in rendered


def test_model_policies_have_bounded_retries_timeouts_and_budgets() -> None:
    for operation in (
        "generation",
        "book_plan",
        "chapter_review",
        "style_analysis",
        "knowledge_build",
    ):
        policy = get_model_policy(operation)
        assert 0 <= policy.max_retries <= 5
        assert 0 < policy.timeout_seconds <= 600
        assert policy.max_tokens > 0
        assert policy.prompt_max_chars > 0
