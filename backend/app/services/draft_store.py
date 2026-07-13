from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import settings
from app.services.file_ops import atomic_write_json, atomic_write_text
from app.models.schemas import (
    ContinuityCheckResult,
    ContinuityIssue,
    DraftDetail,
    DraftMeta,
    DraftVersion,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _word_count(text: str) -> int:
    return len("".join(text.split()))


class DraftStore:
    def __init__(
        self,
        root: Path | None = None,
        *,
        project_id: str = "longzu_continuation",
        title: str = "本地续写草稿",
    ) -> None:
        self.project_id = project_id
        self.project_title = title
        self.root = Path(root or settings.continuation_project_dir)
        self.manifest_path = self.root / "manifest.json"
        self.drafts_dir = self.root / "drafts"
        self.generations_dir = self.root / "generations"
        self.versions_dir = self.root / "versions"
        self.exports_dir = self.root / "exports"
        self._lock = RLock()
        self._ensure_project()

    def set_root(self, root: Path) -> None:
        with self._lock:
            self.root = Path(root)
            self.manifest_path = self.root / "manifest.json"
            self.drafts_dir = self.root / "drafts"
            self.generations_dir = self.root / "generations"
            self.versions_dir = self.root / "versions"
            self.exports_dir = self.root / "exports"
            self._ensure_project()

    def _ensure_project(self) -> None:
        for directory in (
            self.root,
            self.drafts_dir,
            self.generations_dir,
            self.versions_dir,
            self.exports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            now = _now().isoformat()
            self._write_json(
                self.manifest_path,
                {
                    "project_id": self.project_id,
                    "title": self.project_title,
                    "created_at": now,
                    "updated_at": now,
                    "chapters": [],
                },
            )

    def _read_manifest(self) -> dict[str, Any]:
        self._ensure_project()
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"草稿工程 manifest 无法读取: {exc}") from exc
        if not isinstance(data.get("chapters"), list):
            data["chapters"] = []
        return data

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = _now().isoformat()
        self._write_json(self.manifest_path, manifest)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        atomic_write_json(path, value)

    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        atomic_write_text(path, value)

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("草稿 ID 格式不安全")
        return value

    def _draft_path(self, draft_id: str) -> Path:
        safe_id = self._validate_id(draft_id)
        return self.drafts_dir / f"{safe_id}.md"

    def _find_meta(self, manifest: dict[str, Any], draft_id: str) -> dict[str, Any]:
        self._validate_id(draft_id)
        for item in manifest["chapters"]:
            if item.get("draft_id") == draft_id:
                return item
        raise KeyError(draft_id)

    def list_drafts(self) -> list[DraftMeta]:
        with self._lock:
            manifest = self._read_manifest()
            return [
                DraftMeta.model_validate(item)
                for item in sorted(
                    manifest["chapters"],
                    key=lambda value: value.get("updated_at", ""),
                    reverse=True,
                )
            ]

    def create_draft(
        self,
        *,
        title: str,
        source_anchor_chapter_id: str,
        notes: str = "",
    ) -> DraftDetail:
        with self._lock:
            manifest = self._read_manifest()
            existing_numbers = []
            for item in manifest["chapters"]:
                match = re.fullmatch(r"chapter_(\d+)", str(item.get("draft_id", "")))
                if match:
                    existing_numbers.append(int(match.group(1)))
            draft_id = f"chapter_{max(existing_numbers, default=0) + 1:03d}"
            now = _now()
            path = self._draft_path(draft_id)
            self._write_text(path, "")
            item = {
                "draft_id": draft_id,
                "title": title.strip(),
                "source_anchor_chapter_id": source_anchor_chapter_id,
                "notes": notes,
                "word_count": 0,
                "status": "draft",
                "file_path": f"drafts/{path.name}",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            manifest["chapters"].append(item)
            self._write_manifest(manifest)
            return DraftDetail(**item, content="")

    def get_draft(self, draft_id: str) -> DraftDetail:
        with self._lock:
            manifest = self._read_manifest()
            item = self._find_meta(manifest, draft_id)
            path = self._draft_path(draft_id)
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            return DraftDetail(**item, content=content)

    def save_draft(
        self,
        draft_id: str,
        *,
        title: str,
        content: str,
        notes: str = "",
    ) -> DraftDetail:
        with self._lock:
            manifest = self._read_manifest()
            item = self._find_meta(manifest, draft_id)
            path = self._draft_path(draft_id)
            self._write_text(path, content)
            item.update(
                {
                    "title": title.strip(),
                    "notes": notes,
                    "word_count": _word_count(content),
                    "updated_at": _now().isoformat(),
                }
            )
            self._write_manifest(manifest)
            return DraftDetail(**item, content=content)

    def append_to_draft(
        self,
        draft_id: str,
        generated_text: str,
    ) -> DraftDetail:
        with self._lock:
            current = self.get_draft(draft_id)
            self.create_version(draft_id)
            separator = "\n\n" if current.content.strip() else ""
            content = f"{current.content.rstrip()}{separator}{generated_text.strip()}\n"
            return self.save_draft(
                draft_id,
                title=current.title,
                content=content,
                notes=current.notes,
            )

    def create_version(self, draft_id: str) -> DraftVersion:
        with self._lock:
            current = self.get_draft(draft_id)
            prefix = f"{draft_id}_v"
            numbers = []
            for path in self.versions_dir.glob(f"{prefix}*.md"):
                match = re.fullmatch(
                    rf"{re.escape(prefix)}(\d+)\.md",
                    path.name,
                )
                if match:
                    numbers.append(int(match.group(1)))
            version_number = max(numbers, default=0) + 1
            version_id = f"{draft_id}_v{version_number}"
            path = self.versions_dir / f"{version_id}.md"
            self._write_text(path, current.content)
            metadata = {
                "version_id": version_id,
                "draft_id": draft_id,
                "file_path": f"versions/{path.name}",
                "word_count": current.word_count,
                "created_at": _now().isoformat(),
            }
            self._write_json(path.with_suffix(".json"), metadata)
            return DraftVersion.model_validate(metadata)

    def list_versions(self, draft_id: str) -> list[DraftVersion]:
        self._validate_id(draft_id)
        with self._lock:
            self.get_draft(draft_id)
            versions: list[DraftVersion] = []
            for path in self.versions_dir.glob(f"{draft_id}_v*.json"):
                try:
                    versions.append(
                        DraftVersion.model_validate(
                            json.loads(path.read_text(encoding="utf-8"))
                        )
                    )
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
            return sorted(versions, key=lambda item: item.created_at, reverse=True)

    def export_draft(self, draft_id: str, export_format: str) -> Path:
        if export_format not in {"md", "txt"}:
            raise ValueError("导出格式只支持 md 或 txt")
        with self._lock:
            current = self.get_draft(draft_id)
            path = self.exports_dir / f"{draft_id}.{export_format}"
            content = current.content
            if export_format == "md":
                content = f"# {current.title}\n\n{content.lstrip()}"
            self._write_text(path, content)
            return path

    def save_generation(self, generation_id: str, payload: dict[str, Any]) -> None:
        safe_id = self._validate_id(generation_id)
        with self._lock:
            self._write_json(self.generations_dir / f"gen_{safe_id}.json", payload)

    def load_generation(self, generation_id: str) -> dict[str, Any] | None:
        safe_id = self._validate_id(generation_id)
        path = self.generations_dir / f"gen_{safe_id}.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def list_generations(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        with self._lock:
            for path in self.generations_dir.glob("gen_*.json"):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        values.append(value)
                except (OSError, json.JSONDecodeError):
                    continue
        return sorted(values, key=lambda item: item.get("created_at", ""), reverse=True)

    def update_generation(self, generation_id: str, **updates: Any) -> None:
        with self._lock:
            value = self.load_generation(generation_id)
            if value is None:
                return
            value.update(updates)
            self.save_generation(generation_id, value)

    def delete_generation(self, generation_id: str) -> bool:
        safe_id = self._validate_id(generation_id)
        path = self.generations_dir / f"gen_{safe_id}.json"
        with self._lock:
            if not path.exists():
                return False
            path.unlink()
            return True

    def check_continuity(self, draft_id: str) -> ContinuityCheckResult:
        from app.services.planning_store import planning_store

        with self._lock:
            draft = self.get_draft(draft_id)
            issues: list[ContinuityIssue] = []
            content = draft.content.strip()
            if not content:
                issues.append(
                    ContinuityIssue(
                        level="error",
                        code="empty_draft",
                        message="当前草稿为空，尚无正文可检查。",
                    )
                )
            elif draft.word_count < 500:
                issues.append(
                    ContinuityIssue(
                        level="warning",
                        code="short_draft",
                        message=f"当前草稿仅 {draft.word_count} 字，作为完整章节偏短。",
                    )
                )

            paragraphs = [
                re.sub(r"\s+", "", item)
                for item in re.split(r"\n\s*\n", content)
                if len(re.sub(r"\s+", "", item)) >= 30
            ]
            repeated = sorted(
                {item for item in paragraphs if paragraphs.count(item) > 1}
            )
            if repeated:
                issues.append(
                    ContinuityIssue(
                        level="warning",
                        code="duplicate_paragraphs",
                        message=f"发现 {len(repeated)} 处完全重复的较长段落。",
                    )
                )

            plans = planning_store.list_plans()
            plan = next(
                (item for item in plans if item.draft_id == draft_id),
                None,
            )
            if plan is None:
                issues.append(
                    ContinuityIssue(
                        level="warning",
                        code="missing_plan",
                        message="当前草稿尚未绑定章节规划。",
                    )
                )
            elif content:
                goal_keywords = _keywords(plan.chapter_goal)
                if goal_keywords and not any(word in content for word in goal_keywords):
                    issues.append(
                        ContinuityIssue(
                            level="warning",
                            code="goal_alignment",
                            message="正文中未发现章节目标的明显关键词，请人工确认是否偏离规划。",
                        )
                    )
                hook_keywords = _keywords(plan.ending_hook)
                ending = content[-800:]
                if plan.ending_hook and hook_keywords and not any(
                    word in ending for word in hook_keywords
                ):
                    issues.append(
                        ContinuityIssue(
                            level="warning",
                            code="ending_hook",
                            message="草稿结尾尚未明显体现规划中的章末钩子。",
                        )
                    )
                elif not plan.ending_hook:
                    issues.append(
                        ContinuityIssue(
                            level="warning",
                            code="missing_ending_hook",
                            message="章节规划尚未设置章末钩子。",
                        )
                    )

            pending_generations = [
                item
                for item in self.list_generations()
                if not item.get("accepted")
                and (
                    item.get("request", {}).get("draft_id") == draft_id
                    or item.get("accepted_draft_id") == draft_id
                )
                and str(item.get("content", "")).strip()
            ]
            if pending_generations:
                issues.append(
                    ContinuityIssue(
                        level="warning",
                        code="unaccepted_generation",
                        message=f"有 {len(pending_generations)} 条生成结果尚未接受到当前草稿。",
                    )
                )

            duplicate_titles = [
                item
                for item in self.list_drafts()
                if item.draft_id != draft_id and item.title.strip() == draft.title.strip()
            ]
            if duplicate_titles:
                issues.append(
                    ContinuityIssue(
                        level="warning",
                        code="duplicate_title",
                        message=f"另有 {len(duplicate_titles)} 个草稿使用相同标题。",
                    )
                )

            return ContinuityCheckResult(
                draft_id=draft_id,
                passed=not any(item.level == "error" for item in issues),
                word_count=draft.word_count,
                issues=issues,
                checked_at=_now(),
            )


def _keywords(text: str) -> list[str]:
    values = re.split(r"[\s，。；：、,.!?！？;:（）()\[\]【】]+", text)
    return [value for value in values if 2 <= len(value) <= 12][:12]


from app.services.project_context import ProjectScopedStore
from app.services.project_store import project_store


def _project_draft_store(project_id: str) -> DraftStore:
    project = project_store.get(project_id)
    return DraftStore(
        project_store.layout(project_id).draft_store,
        project_id=project_id,
        title=project.title,
    )


draft_store = ProjectScopedStore(DraftStore(), _project_draft_store)
