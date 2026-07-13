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
    BookPlan,
    GenerationResult,
    OfficialChapter,
    OfficialChapterSaveRequest,
    OfficialChapterUpdateRequest,
    TempGeneration,
    TempGenerationCreate,
    WritingProjectManifest,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _word_count(text: str) -> int:
    return len("".join(text.split()))


class WritingProjectStore:
    def __init__(
        self,
        root: Path | None = None,
        *,
        project_id: str = "longzu6",
        title: str = "本地续写项目",
        legacy_layout: bool = True,
    ) -> None:
        self.project_id = project_id
        self.project_title = title
        self.legacy_layout = legacy_layout
        self._lock = RLock()
        self.set_root(Path(root or settings.writing_project_dir))

    def set_root(self, root: Path) -> None:
        with self._lock:
            self.root = Path(root)
            self.book_plan_dir = self.root / "book_plan"
            self.official_dir = self.root / "official_chapters"
            self.temp_dir = self.root / "temp_generations"
            self.revisions_dir = self.root / "revisions"
            self.exports_dir = self.root / "exports"
            self.manifest_path = self.root / "manifest.json"
            self._ensure_project()

    def _ensure_project(self) -> None:
        for directory in (
            self.root,
            self.book_plan_dir,
            self.official_dir,
            self.temp_dir,
            self.revisions_dir,
            self.exports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self._write_json(
                self.manifest_path,
                WritingProjectManifest(
                    project_id=self.project_id,
                    title=self.project_title,
                ).model_dump(mode="json"),
            )

    def _book_plan_stem(self) -> str:
        return "longzu6_plan" if self.legacy_layout else "book_plan"

    def _path_label(self, path: Path) -> str:
        if self.legacy_layout:
            return f"writing_projects/longzu6/{path.relative_to(self.root).as_posix()}"
        return f"writing/{path.relative_to(self.root).as_posix()}"

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        atomic_write_json(path, value)

    @staticmethod
    def _write_text(path: Path, value: str) -> None:
        atomic_write_text(path, value)

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("文件 ID 格式不安全")
        return value

    def get_manifest(self) -> WritingProjectManifest:
        with self._lock:
            self._ensure_project()
            try:
                return WritingProjectManifest.model_validate_json(
                    self.manifest_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"写作项目 manifest 无法读取: {exc}") from exc

    def _update_manifest(self, **updates: Any) -> WritingProjectManifest:
        current = self.get_manifest()
        manifest = current.model_copy(
            update={
                **updates,
                "official_chapter_count": len(self.list_official_chapters()),
                "temp_generation_count": len(self.list_temp_generations()),
                "updated_at": _now(),
            }
        )
        self._write_json(self.manifest_path, manifest.model_dump(mode="json"))
        return manifest

    def save_book_plan(self, plan: BookPlan) -> BookPlan:
        with self._lock:
            stem = self._book_plan_stem()
            json_path = self.book_plan_dir / f"{stem}.json"
            md_path = self.book_plan_dir / f"{stem}.md"
            saved = plan.model_copy(
                update={
                    "project_id": self.project_id,
                    "file_path": self._path_label(json_path),
                    "updated_at": _now(),
                }
            )
            self._write_json(json_path, saved.model_dump(mode="json"))
            self._write_text(md_path, self._book_plan_markdown(saved))
            self._update_manifest(
                book_plan_accepted=saved.accepted,
                book_plan_file_path=saved.file_path,
            )
            return saved

    def load_book_plan(self) -> BookPlan | None:
        path = self.book_plan_dir / f"{self._book_plan_stem()}.json"
        if not path.exists():
            return None
        try:
            return BookPlan.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"总体构想文件无法读取: {exc}") from exc

    def accept_book_plan(self, plan: BookPlan) -> BookPlan:
        with self._lock:
            accepted = plan.model_copy(
                update={"accepted": True, "accepted_at": _now(), "updated_at": _now()}
            )
            saved = self.save_book_plan(accepted)
            for record in self.list_temp_generations():
                if (
                    record.record_type == "book_plan"
                    and record.generation_id == plan.book_plan_id
                    and not record.accepted
                ):
                    updated = record.model_copy(
                        update={"accepted": True, "updated_at": _now()}
                    )
                    self._write_json(
                        self.temp_dir / f"{record.temp_id}.json",
                        updated.model_dump(mode="json"),
                    )
            return saved

    @staticmethod
    def _book_plan_markdown(plan: BookPlan) -> str:
        lines = [
            f"# {plan.title}",
            "",
            f"- 状态：{'已接受' if plan.accepted else '待审核'}",
            f"- 预计章节：{len(plan.chapters)}",
            f"- 原文锚点：{plan.source_anchor_chapter_id}",
            "",
            "## 故事概要",
            plan.premise,
            "",
            "## 核心主题",
            plan.core_theme,
            "",
            "## 重点人物",
            "\n".join(f"- {item}" for item in plan.focus_characters),
            "",
            "## 主线冲突",
            plan.main_conflict,
            "",
            "## 暗线冲突",
            plan.hidden_conflict,
            "",
            "## 核心谜团",
            plan.central_mystery,
            "",
            "## 与既有作品的关系",
            plan.relation_to_previous_books,
            "",
            "## 开局",
            plan.opening_setup,
            "",
            "## 中段转折",
            plan.midpoint_turn,
            "",
            "## 结尾方向",
            plan.ending_direction,
            "",
            "## 章节安排",
        ]
        for chapter in sorted(plan.chapters, key=lambda item: item.order):
            lines.extend(
                [
                    "",
                    f"### 第 {chapter.order} 章 {chapter.title}",
                    chapter.chapter_goal,
                    "",
                    f"- 作用：{'、'.join(chapter.chapter_function)}",
                    f"- 人物：{'、'.join(chapter.characters)}",
                    f"- 冲突：{chapter.conflict}",
                    f"- 埋伏笔：{'、'.join(chapter.foreshadowing_to_plant)}",
                    f"- 回收伏笔：{'、'.join(chapter.foreshadowing_to_resolve)}",
                    f"- 章末钩子：{chapter.ending_hook}",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def save_generation_result(
        self,
        result: GenerationResult,
        *,
        record_type: str | None = None,
        chapter_order: int = 0,
        chapter_title: str = "",
        completeness_check: dict | None = None,
        chapter_plan_snapshot: dict | None = None,
    ) -> TempGeneration:
        generation_request = result.request.model_dump(mode="json")
        if completeness_check is not None:
            generation_request["_completeness_check"] = completeness_check
        if chapter_plan_snapshot is not None:
            generation_request["_chapter_plan_snapshot"] = chapter_plan_snapshot
        value = TempGenerationCreate(
            generation_id=result.id,
            chapter_order=chapter_order,
            chapter_title=chapter_title or result.suggested_title,
            record_type=record_type or result.request.generation_kind,
            content=result.content,
            source_plan_id=result.request.plan_id,
            generation_request=generation_request,
            generation_status=(
                "partial_success" if result.is_partial else "success"
            ),
            warning=result.warning,
            can_save=bool(result.content.strip()),
            can_repair=result.can_repair,
        )
        return self.create_temp_generation(value)

    def save_book_plan_record(self, plan: BookPlan) -> TempGeneration:
        return self.create_temp_generation(
            TempGenerationCreate(
                generation_id=plan.book_plan_id,
                chapter_title=plan.title,
                record_type="book_plan",
                content=self._book_plan_markdown(plan),
                generation_request={
                    "source_anchor_chapter_id": plan.source_anchor_chapter_id,
                    "target_chapter_count": plan.target_chapter_count,
                },
            )
        )

    def save_raw_book_plan(
        self,
        *,
        raw_text: str,
        request: dict,
        error_message: str,
        model_name: str,
        prompt_chars: int,
    ) -> TempGeneration:
        with self._lock:
            timestamp = _now().strftime("%Y%m%d_%H%M%S_%f")
            temp_id = f"book_plan_raw_{timestamp}"
            md_path = self.temp_dir / f"{temp_id}.md"
            json_path = self.temp_dir / f"{temp_id}.json"
            now = _now()
            md_relative = self._path_label(md_path)
            json_relative = self._path_label(json_path)
            record = TempGeneration(
                temp_id=temp_id,
                generation_id=temp_id,
                chapter_title="总体构想原始文本",
                record_type="book_plan_raw",
                content=raw_text,
                word_count=_word_count(raw_text),
                generation_request={
                    **request,
                    "parse_error": error_message,
                    "model_name": model_name,
                    "prompt_chars": prompt_chars,
                    "raw_json_path": json_relative,
                },
                file_path=md_relative,
                created_at=now,
                updated_at=now,
            )
            self._write_text(md_path, raw_text.strip() + "\n")
            self._write_json(json_path, record.model_dump(mode="json"))
            self._update_manifest()
            return record

    def create_temp_generation(self, value: TempGenerationCreate) -> TempGeneration:
        with self._lock:
            temp_id = self._next_id(self.temp_dir, "temp_", ".json")
            now = _now()
            record = TempGeneration(
                temp_id=temp_id,
                generation_id=value.generation_id or temp_id,
                chapter_order=value.chapter_order,
                chapter_title=value.chapter_title,
                record_type=value.record_type,
                content=value.content,
                word_count=_word_count(value.content),
                source_plan_id=value.source_plan_id,
                generation_request=value.generation_request,
                generation_status=value.generation_status,
                warning=value.warning,
                can_save=value.can_save,
                can_repair=value.can_repair,
                file_path=self._path_label(self.temp_dir / f"{temp_id}.json"),
                created_at=now,
                updated_at=now,
            )
            self._write_json(
                self.temp_dir / f"{temp_id}.json",
                record.model_dump(mode="json"),
            )
            self._update_manifest()
            return record

    def list_temp_generations(self) -> list[TempGeneration]:
        values = []
        paths = list(self.temp_dir.glob("temp_*.json"))
        paths.extend(self.temp_dir.glob("book_plan_raw_*.json"))
        for path in paths:
            try:
                values.append(
                    TempGeneration.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def get_temp_generation(self, temp_id: str) -> TempGeneration:
        safe_id = self._validate_id(temp_id)
        path = self.temp_dir / f"{safe_id}.json"
        if not path.exists():
            raise KeyError(temp_id)
        return TempGeneration.model_validate_json(path.read_text(encoding="utf-8"))

    def attach_generation_metadata(
        self,
        generation_id: str,
        key: str,
        value: Any,
    ) -> TempGeneration | None:
        with self._lock:
            record = next(
                (
                    item
                    for item in self.list_temp_generations()
                    if item.generation_id == generation_id
                ),
                None,
            )
            if record is None:
                return None
            updated = record.model_copy(
                update={
                    "generation_request": {
                        **record.generation_request,
                        key: value,
                    },
                    "updated_at": _now(),
                }
            )
            self._write_json(
                self.temp_dir / f"{updated.temp_id}.json",
                updated.model_dump(mode="json"),
            )
            return updated

    def delete_temp_generation(self, temp_id: str) -> bool:
        safe_id = self._validate_id(temp_id)
        path = self.temp_dir / f"{safe_id}.json"
        with self._lock:
            if not path.exists():
                return False
            record = TempGeneration.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            path.unlink()
            if record.record_type == "book_plan_raw":
                (self.temp_dir / f"{safe_id}.md").unlink(missing_ok=True)
            self._update_manifest()
            return True

    def save_official_chapter(
        self,
        value: OfficialChapterSaveRequest,
    ) -> OfficialChapter:
        with self._lock:
            if value.official_chapter_id:
                current = self.get_official_chapter(value.official_chapter_id)
                self._create_revision(current)
                chapter_id = current.chapter_id
                order = current.order
                created_at = current.created_at
                revision_count = current.revision_count + 1
            else:
                existing = self.list_official_chapters()
                order = value.chapter_order or (
                    max((item.order for item in existing), default=0) + 1
                )
                chapter_id = f"chapter_{order:03d}"
                if any(item.order == order for item in existing):
                    raise ValueError(
                        f"第 {order} 章已存在，请从正式章节库打开后再修改"
                    )
                created_at = _now()
                revision_count = 0
            path = self.official_dir / f"{chapter_id}.md"
            now = _now()
            warning_items = value.completeness_check.get("warnings", [])
            warning_messages = [
                str(item.get("message", "")).strip()
                for item in warning_items
                if isinstance(item, dict) and str(item.get("message", "")).strip()
            ]
            blocking_items = value.completeness_check.get("blocking_errors", [])
            completeness_passed = (
                not bool(blocking_items)
                if "blocking_errors" in value.completeness_check
                else bool(value.completeness_check.get("passed", True))
            )
            self._write_text(
                path,
                f"# {value.title.strip()}\n\n{value.content.strip()}\n",
            )
            chapter = OfficialChapter(
                chapter_id=chapter_id,
                order=order,
                title=value.title.strip(),
                content=value.content.strip(),
                word_count=_word_count(value.content),
                file_path=self._path_label(path),
                source_generation_id=value.source_generation_id,
                source_plan_id=value.source_plan_id,
                completeness_passed=completeness_passed,
                saved_with_warnings=bool(warning_messages),
                warnings=warning_messages,
                chapter_plan_snapshot=value.chapter_plan_snapshot,
                revision_count=revision_count,
                created_at=created_at,
                updated_at=now,
            )
            self._write_json(
                self.official_dir / f"{chapter_id}.json",
                chapter.model_dump(mode="json", exclude={"content"}),
            )
            if value.source_temp_id:
                self._mark_temp_official(value.source_temp_id, chapter_id)
            self._update_manifest()
            return chapter

    def update_official_chapter(
        self,
        chapter_id: str,
        value: OfficialChapterUpdateRequest,
    ) -> OfficialChapter:
        current = self.get_official_chapter(chapter_id)
        return self.save_official_chapter(
            OfficialChapterSaveRequest(
                title=value.title,
                content=value.content,
                chapter_order=current.order,
                source_generation_id=current.source_generation_id,
                source_plan_id=current.source_plan_id,
                official_chapter_id=current.chapter_id,
                completeness_check={
                    "passed": current.completeness_passed,
                    "blocking_errors": [],
                    "warnings": [
                        {"level": "warning", "code": "saved_warning", "message": item}
                        for item in current.warnings
                    ],
                },
                chapter_plan_snapshot=current.chapter_plan_snapshot,
            )
        )

    def list_official_chapters(self) -> list[OfficialChapter]:
        values = []
        for path in self.official_dir.glob("chapter_*.json"):
            try:
                meta = OfficialChapter.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                values.append(meta)
            except (OSError, ValueError):
                continue
        return sorted(values, key=lambda item: item.order)

    def get_official_chapter(self, chapter_id: str) -> OfficialChapter:
        safe_id = self._validate_id(chapter_id)
        meta_path = self.official_dir / f"{safe_id}.json"
        text_path = self.official_dir / f"{safe_id}.md"
        if not meta_path.exists() or not text_path.exists():
            raise KeyError(chapter_id)
        meta = OfficialChapter.model_validate_json(meta_path.read_text(encoding="utf-8"))
        raw = text_path.read_text(encoding="utf-8")
        content = re.sub(r"^# .+?\r?\n\r?\n", "", raw, count=1).rstrip()
        return meta.model_copy(update={"content": content})

    def get_official_chapter_by_order(self, order: int) -> OfficialChapter | None:
        chapter = next(
            (item for item in self.list_official_chapters() if item.order == order),
            None,
        )
        return self.get_official_chapter(chapter.chapter_id) if chapter else None

    def delete_official_chapter(self, chapter_id: str) -> bool:
        safe_id = self._validate_id(chapter_id)
        meta_path = self.official_dir / f"{safe_id}.json"
        text_path = self.official_dir / f"{safe_id}.md"
        with self._lock:
            if not meta_path.exists() and not text_path.exists():
                return False
            meta_path.unlink(missing_ok=True)
            text_path.unlink(missing_ok=True)
            self._update_manifest()
            return True

    def export_official_chapter(self, chapter_id: str, export_format: str) -> Path:
        if export_format not in {"md", "txt"}:
            raise ValueError("导出格式只支持 md 或 txt")
        chapter = self.get_official_chapter(chapter_id)
        path = self.exports_dir / f"{chapter.chapter_id}.{export_format}"
        content = chapter.content
        if export_format == "md":
            content = f"# {chapter.title}\n\n{content}\n"
        self._write_text(path, content)
        return path

    def create_editor_record_from_official(self, chapter_id: str) -> TempGeneration:
        chapter = self.get_official_chapter(chapter_id)
        return self.create_temp_generation(
            TempGenerationCreate(
                generation_id=f"edit_{chapter.chapter_id}_{int(_now().timestamp())}",
                chapter_order=chapter.order,
                chapter_title=chapter.title,
                record_type="official_revision",
                content=chapter.content,
                source_plan_id=chapter.source_plan_id,
                generation_request={
                    "start_chapter_id": "",
                    "source_anchor_chapter_id": "",
                    "plot_direction": "",
                    "target_word_count": max(300, min(5000, chapter.word_count)),
                    "mode": "chapter",
                    "draft_id": "",
                    "plan_id": chapter.source_plan_id,
                    "append_to_draft": False,
                    "reference_chapter_ids": [],
                    "pov_character": "",
                    "additional_instructions": "",
                    "generation_kind": "revision",
                    "official_chapter_id": chapter.chapter_id,
                },
            )
        )

    def _mark_temp_official(self, temp_id: str, chapter_id: str) -> None:
        try:
            record = self.get_temp_generation(temp_id)
        except KeyError:
            return
        updated = record.model_copy(
            update={
                "accepted": True,
                "saved_official": True,
                "official_chapter_id": chapter_id,
                "updated_at": _now(),
            }
        )
        self._write_json(
            self.temp_dir / f"{temp_id}.json",
            updated.model_dump(mode="json"),
        )

    def _create_revision(self, chapter: OfficialChapter) -> Path:
        revision_number = chapter.revision_count + 1
        path = self.revisions_dir / (
            f"{chapter.chapter_id}_v{revision_number}.md"
        )
        self._write_text(path, f"# {chapter.title}\n\n{chapter.content}\n")
        return path

    @staticmethod
    def _next_id(directory: Path, prefix: str, suffix: str) -> str:
        numbers = []
        for path in directory.glob(f"{prefix}*{suffix}"):
            match = re.fullmatch(
                rf"{re.escape(prefix)}(\d+){re.escape(suffix)}",
                path.name,
            )
            if match:
                numbers.append(int(match.group(1)))
        return f"{prefix}{max(numbers, default=0) + 1:06d}"


from app.services.project_context import ProjectScopedStore
from app.services.project_store import project_store


def _project_writing_store(project_id: str) -> WritingProjectStore:
    project = project_store.get(project_id)
    return WritingProjectStore(
        project_store.layout(project_id).writing,
        project_id=project_id,
        title=project.title,
        legacy_layout=False,
    )


writing_project_store = ProjectScopedStore(
    WritingProjectStore(),
    _project_writing_store,
)
