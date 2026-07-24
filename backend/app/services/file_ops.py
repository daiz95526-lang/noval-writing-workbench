from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


_LOCKS_GUARD = RLock()
_PATH_LOCKS: dict[str, RLock] = {}


def _path_lock(path: Path) -> RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, RLock())


@contextmanager
def locked_path(path: Path):
    lock = _path_lock(path)
    with lock:
        yield


def _backup_name(path: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{path.name}.{timestamp}.bak"


def list_backups(path: Path, backup_dir: Path | None = None) -> list[Path]:
    root = backup_dir or path.parent / ".backups"
    if not root.is_dir():
        return []
    return sorted(root.glob(f"{path.name}.*.bak"), reverse=True)


def _create_backup(
    path: Path,
    *,
    backup_dir: Path | None,
    max_backups: int,
) -> Path | None:
    if not path.is_file():
        return None
    root = backup_dir or path.parent / ".backups"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / _backup_name(path)
    shutil.copy2(path, destination)
    for stale in list_backups(path, root)[max(1, max_backups):]:
        stale.unlink(missing_ok=True)
    return destination


def atomic_write_bytes(
    path: Path,
    value: bytes,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    max_backups: int = 5,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    with locked_path(path):
        try:
            with temporary.open("wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            if backup:
                _create_backup(
                    path,
                    backup_dir=backup_dir,
                    max_backups=max_backups,
                )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def atomic_write_text(
    path: Path,
    value: str,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    max_backups: int = 5,
) -> None:
    atomic_write_bytes(
        path,
        value.encode("utf-8"),
        backup=backup,
        backup_dir=backup_dir,
        max_backups=max_backups,
    )


def atomic_write_json(
    path: Path,
    value: Any,
    *,
    backup: bool = True,
    backup_dir: Path | None = None,
    max_backups: int = 5,
) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2),
        backup=backup,
        backup_dir=backup_dir,
        max_backups=max_backups,
    )


def read_json_with_recovery(
    path: Path,
    *,
    default: Any = None,
    restore: bool = True,
) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as original_error:
        for backup in list_backups(path):
            try:
                recovered = json.loads(backup.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if restore:
                atomic_write_json(path, recovered, backup=False)
            return recovered
        raise RuntimeError(f"JSON 文件损坏且没有可用备份: {path.name}") from original_error


def restore_latest_backup(path: Path, backup_dir: Path | None = None) -> Path:
    for backup in list_backups(path, backup_dir):
        try:
            value = backup.read_bytes()
        except OSError:
            continue
        atomic_write_bytes(path, value, backup=False)
        return backup
    raise FileNotFoundError(f"没有可恢复的备份: {path.name}")


def soft_delete(path: Path, trash_root: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(path)
    trash_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = safe_child(trash_root, f"{path.name}.{timestamp}")
    with locked_path(path):
        os.replace(path, destination)
    return destination


def safe_child(root: Path, *parts: str) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("路径超出允许的项目目录")
    return candidate
