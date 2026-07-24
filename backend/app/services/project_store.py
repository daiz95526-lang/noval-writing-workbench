from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

from app.config import settings
from app.models.schemas import (
    CorpusConfig,
    LegacyMigrationPreview,
    LegacyMigrationRequest,
    LegacyMigrationResult,
    Project,
    ProjectCreateRequest,
    ProjectDeleteResult,
    ProjectStatus,
    ProjectSummary,
    ProjectType,
    ProjectUpdateRequest,
)
from app.services.file_ops import atomic_write_json, read_json_with_recovery, safe_child


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _now().strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class ProjectLayout:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "project.json"

    @property
    def corpus(self) -> Path:
        return self.root / "corpus"

    @property
    def corpus_source(self) -> Path:
        return self.corpus / "source"

    @property
    def corpus_processed(self) -> Path:
        return self.corpus / "processed"

    @property
    def corpus_index(self) -> Path:
        return self.corpus / "index"

    @property
    def corpus_reports(self) -> Path:
        return self.corpus / "reports"

    @property
    def analysis(self) -> Path:
        return self.root / "analysis"

    @property
    def analysis_style(self) -> Path:
        return self.analysis / "style"

    @property
    def analysis_knowledge(self) -> Path:
        return self.analysis / "knowledge"

    @property
    def analysis_summaries(self) -> Path:
        return self.analysis / "summaries"

    @property
    def planning(self) -> Path:
        return self.root / "planning"

    @property
    def planning_book_plans(self) -> Path:
        return self.planning / "book_plans"

    @property
    def planning_chapter_plans(self) -> Path:
        return self.planning / "chapter_plans"

    @property
    def writing(self) -> Path:
        return self.root / "writing"

    @property
    def draft_store(self) -> Path:
        return self.writing / "draft_store"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    def managed_directories(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.corpus_source,
            self.corpus_processed,
            self.corpus_index,
            self.corpus_reports,
            self.analysis_style,
            self.analysis_knowledge,
            self.analysis_summaries,
            self.planning_book_plans,
            self.planning_chapter_plans,
            self.writing / "temp_generations",
            self.writing / "drafts",
            self.writing / "official_chapters",
            self.writing / "revisions",
            self.writing / "versions",
            self.exports,
            self.backups,
        )


class ProjectStore:
    def __init__(self, root: Path | None = None) -> None:
        self._lock = RLock()
        self.root = Path(root or settings.projects_dir)

    def set_root(self, root: Path) -> None:
        with self._lock:
            self.root = Path(root)

    def project_path(self, project_id: str) -> Path:
        validated = Project(project_id=project_id, title="validation").project_id
        return safe_child(self.root, validated)

    @staticmethod
    def validate_corpus_config(config: CorpusConfig) -> CorpusConfig:
        if config.mode != "external_readonly":
            return config
        if not config.source_paths:
            raise ValueError("外部只读语料至少需要一个已授权目录")
        allowed_roots = (
            settings.corpus_source_dir.resolve(),
            *(path.resolve() for path in settings.allowed_external_corpus_roots),
        )
        normalized: list[str] = []
        for raw_path in config.source_paths:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                raise ValueError("外部语料目录必须使用绝对路径")
            candidate = candidate.resolve()
            if not candidate.is_dir():
                raise ValueError(f"外部语料目录不存在或不可读取: {candidate}")
            if not any(
                candidate == root or root in candidate.parents
                for root in allowed_roots
            ):
                raise ValueError(
                    "外部语料目录未获授权；请通过 EXTERNAL_CORPUS_ROOTS 配置允许根目录"
                )
            normalized.append(str(candidate))
        return config.model_copy(update={"source_paths": normalized, "read_only": True})

    def layout(self, project_id: str) -> ProjectLayout:
        if project_id == settings.project_id and self._legacy_exists():
            raise ValueError("旧项目没有托管目录；请使用 legacy_layout")
        project = self.get(project_id)
        if project.storage_mode != "managed":
            raise ValueError("该项目不是托管目录项目")
        return ProjectLayout(self.project_path(project.project_id))

    def legacy_layout(self) -> dict[str, Path]:
        return {
            "source": settings.corpus_source_dir,
            "processed": settings.processed_dir,
            "index": settings.data_dir / "chapters_meta.json",
            "reports": settings.corpus_source_dir.parent,
            "analysis": settings.analysis_dir,
            "style": settings.style_cache_dir,
            "planning": settings.continuation_project_dir,
            "writing": settings.writing_project_dir,
        }

    def _legacy_exists(self) -> bool:
        paths = self.legacy_layout()
        if paths["index"].is_file():
            return True

        content_roots = (
            paths["source"],
            paths["processed"],
            paths["analysis"],
            paths["style"],
        )
        if any(
            root.is_file()
            or (
                root.is_dir()
                and next(
                    (item for item in root.rglob("*") if item.is_file()),
                    None,
                )
                is not None
            )
            for root in content_roots
        ):
            return True

        planning = paths["planning"]
        if planning.is_dir():
            for path in planning.rglob("*"):
                if not path.is_file():
                    continue
                if path.name not in {
                    "chapter_plans.json",
                    "outline.json",
                    "manifest.json",
                }:
                    return True
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return True
                if path.name == "chapter_plans.json" and bool(payload):
                    return True
                if path.name == "manifest.json" and bool(
                    isinstance(payload, dict) and payload.get("chapters")
                ):
                    return True
                if path.name == "outline.json" and isinstance(payload, dict):
                    outline_fields = (
                        "premise",
                        "main_conflict",
                        "tone",
                        "ending_direction",
                        "continuity_notes",
                        "foreshadowing",
                        "character_arcs",
                        "prohibitions",
                    )
                    if any(payload.get(field) for field in outline_fields):
                        return True

        writing = paths["writing"]
        writing_content_roots = (
            writing / "book_plan",
            writing / "official_chapters",
            writing / "temp_generations",
            writing / "revisions",
            writing / "exports",
        )
        return any(
            root.is_dir() and next((item for item in root.rglob("*") if item.is_file()), None)
            for root in writing_content_roots
        )

    def _legacy_project(self) -> Project:
        return Project(
            project_id=settings.project_id,
            title="本地续写项目",
            description="由旧版 NOVAL 本地目录兼容加载的项目。",
            project_type=ProjectType.CONTINUATION,
            corpus_config=CorpusConfig(
                mode="external_readonly",
                source_paths=[str(settings.corpus_source_dir)],
                read_only=True,
            ),
            model_config_ref={"scope": "global"},
            metadata={
                "legacy_project_title": settings.project_title,
                "legacy_paths_preserved": True,
            },
            storage_mode="legacy",
            legacy=True,
            migration_state="available",
        )

    def list_projects(self, include_archived: bool = True) -> list[Project]:
        with self._lock:
            projects: list[Project] = []
            if self.root.exists():
                for manifest in sorted(self.root.glob("*/project.json")):
                    try:
                        project = Project.model_validate(
                            read_json_with_recovery(manifest)
                        )
                    except (OSError, ValueError):
                        continue
                    if include_archived or project.status == ProjectStatus.ACTIVE:
                        projects.append(project)
            if self._legacy_exists() and not any(
                item.project_id == settings.project_id for item in projects
            ):
                projects.append(self._legacy_project())
            return sorted(
                projects,
                key=lambda item: (item.status != ProjectStatus.ACTIVE, -item.updated_at.timestamp()),
            )

    def get(self, project_id: str) -> Project:
        validated = Project(project_id=project_id, title="validation").project_id
        if validated == settings.project_id and self._legacy_exists():
            managed_manifest = self.project_path(validated) / "project.json"
            if not managed_manifest.exists():
                return self._legacy_project()
        manifest = self.project_path(validated) / "project.json"
        if not manifest.is_file():
            raise KeyError(validated)
        try:
            return Project.model_validate(read_json_with_recovery(manifest))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"项目清单无法读取: {validated}") from exc

    def create(self, request: ProjectCreateRequest) -> Project:
        with self._lock:
            corpus_config = self.validate_corpus_config(request.corpus_config)
            normalized_title = request.title.strip().casefold()
            if any(
                project.title.strip().casefold() == normalized_title
                and project.status == ProjectStatus.ACTIVE
                and project.storage_mode == "managed"
                for project in self.list_projects(include_archived=False)
            ):
                raise ValueError("已存在同名的活动项目，请使用不同名称")
            project_id = request.project_id or uuid.uuid4().hex
            project_id = Project(project_id=project_id, title=request.title).project_id
            target = self.project_path(project_id)
            if target.exists() or (
                project_id == settings.project_id and self._legacy_exists()
            ):
                raise FileExistsError(project_id)
            now = _now()
            project = Project(
                project_id=project_id,
                title=request.title.strip(),
                description=request.description.strip(),
                project_type=request.project_type,
                created_at=now,
                updated_at=now,
                corpus_config=corpus_config,
                model_config_ref=request.model_config_ref,
                metadata=request.metadata,
            )
            layout = ProjectLayout(target)
            try:
                for directory in layout.managed_directories():
                    directory.mkdir(parents=True, exist_ok=True)
                atomic_write_json(layout.manifest, project.model_dump(mode="json"))
            except Exception:
                failed_root = safe_child(self.root, ".failed")
                failed_root.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.replace(failed_root / f"{project_id}-{_timestamp()}")
                raise
            return project

    def update(self, project_id: str, request: ProjectUpdateRequest) -> Project:
        with self._lock:
            project = self.get(project_id)
            if project.storage_mode == "legacy":
                raise PermissionError("旧项目需要迁移后才能修改项目清单")
            values = request.model_dump(exclude_unset=True)
            if "corpus_config" in values:
                if request.corpus_config is None:
                    values.pop("corpus_config")
                else:
                    values["corpus_config"] = self.validate_corpus_config(
                        request.corpus_config
                    )
            values["updated_at"] = _now()
            updated = project.model_copy(update=values)
            atomic_write_json(
                self.layout(project_id).manifest,
                updated.model_dump(mode="json"),
            )
            return updated

    def archive(self, project_id: str) -> Project:
        with self._lock:
            project = self.get(project_id)
            if project.storage_mode == "legacy":
                raise PermissionError("旧项目不能直接归档；请先迁移")
            archived = project.model_copy(
                update={"status": ProjectStatus.ARCHIVED, "updated_at": _now()}
            )
            atomic_write_json(
                self.layout(project_id).manifest,
                archived.model_dump(mode="json"),
            )
            return archived

    def create_backup(self, project_id: str, reason: str) -> Path:
        project = self.get(project_id)
        if project.storage_mode != "managed":
            raise ValueError("旧项目备份由迁移备份流程处理")
        layout = self.layout(project_id)
        backup = layout.backups / f"{project_id}-{reason}-{_timestamp()}.zip"
        temporary = backup.with_name(f".{backup.name}.{uuid.uuid4().hex}.tmp")
        layout.backups.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in layout.root.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                if layout.backups in path.parents:
                    continue
                archive.write(path, path.relative_to(layout.root).as_posix())
        temporary.replace(backup)
        return backup

    def delete(self, project_id: str, confirmation: str) -> ProjectDeleteResult:
        with self._lock:
            if confirmation != project_id:
                raise PermissionError("删除确认值必须与 project_id 完全一致")
            project = self.get(project_id)
            if project.storage_mode == "legacy":
                raise PermissionError("旧项目不能通过 API 删除")
            backup = self.create_backup(project_id, "pre-delete")
            source = self.layout(project_id).root
            trash_root = safe_child(self.root, ".trash")
            trash_root.mkdir(parents=True, exist_ok=True)
            target = safe_child(trash_root, f"{project_id}-{_timestamp()}")
            source.replace(target)
            return ProjectDeleteResult(
                project_id=project_id,
                backup_path=str(target / "backups" / backup.name),
                trash_path=str(target),
            )

    def summary(self, project_id: str, active_task_count: int = 0) -> ProjectSummary:
        project = self.get(project_id)
        if project.storage_mode == "legacy":
            stats = self._chapter_stats(self.legacy_layout()["index"])
            writing = self.legacy_layout()["writing"]
        else:
            layout = self.layout(project_id)
            stats = self._chapter_stats(layout.corpus_index / "chapters_meta.json")
            writing = layout.writing
        return ProjectSummary(
            project_id=project.project_id,
            title=project.title,
            status=project.status,
            storage_mode=project.storage_mode,
            corpus_chapter_count=stats[0],
            corpus_word_count=stats[1],
            temp_generation_count=self._count_files(writing / "temp_generations", "*.json"),
            official_chapter_count=self._count_files(
                writing / "official_chapters", "*.json"
            ),
            active_task_count=active_task_count,
            current_chapter_id=project.current_chapter_id,
        )

    def migration_preview(self, project_id: str) -> LegacyMigrationPreview:
        project = self.get(project_id)
        if project.storage_mode != "legacy":
            raise ValueError("只有旧目录项目需要迁移预览")
        paths = self.legacy_layout()
        chapter_count, total_words = self._chapter_stats(paths["index"])
        derived = [
            paths["processed"],
            paths["index"],
            paths["reports"] / "import_report.json",
            paths["reports"] / "chapter_audit_report.json",
            paths["reports"] / "chapter_audit_report.md",
            paths["analysis"],
            paths["style"],
        ]
        writable = [paths["planning"], paths["writing"]]
        derived_count, derived_bytes = self._measure(derived)
        writable_count, writable_bytes = self._measure(writable)
        source_count, source_bytes = self._measure([paths["source"]])
        warnings = [
            "迁移不会自动开始，不会删除或移动旧目录。",
            "默认引用原始语料，不重复复制大文件。",
        ]
        if source_count == 0:
            warnings.append("未发现原始语料文件；迁移后仍可作为原创项目使用。")
        return LegacyMigrationPreview(
            source_project_id=project.project_id,
            source_paths=[str(path) for path in paths.values() if path.exists()],
            chapter_count=chapter_count,
            total_words=total_words,
            derived_file_count=derived_count,
            writable_file_count=writable_count,
            estimated_copy_bytes=derived_bytes + writable_bytes,
            source_corpus_bytes=source_bytes,
            warnings=warnings,
        )

    def migrate_legacy(
        self,
        project_id: str,
        request: LegacyMigrationRequest,
    ) -> LegacyMigrationResult:
        with self._lock:
            if request.confirm_source_project_id != project_id:
                raise PermissionError("迁移确认值与旧项目 ID 不一致")
            preview = self.migration_preview(project_id)
            paths = self.legacy_layout()
            backup = self._backup_legacy(paths, project_id)
            source_paths = (
                []
                if request.corpus_mode == "copy"
                else [str(paths["source"])] if paths["source"].exists() else []
            )
            target = self.create(
                ProjectCreateRequest(
                    project_id=request.target_project_id,
                    title=request.title,
                    project_type=ProjectType.CONTINUATION,
                    corpus_config=CorpusConfig(
                        mode=(
                            "managed"
                            if request.corpus_mode == "copy"
                            else "external_readonly"
                        ),
                        source_paths=source_paths,
                        read_only=True,
                    ),
                    metadata={
                        "migrated_from": project_id,
                        "legacy_backup": str(backup),
                    },
                )
            )
            layout = self.layout(target.project_id)
            target = target.model_copy(
                update={"migration_state": "in_progress", "updated_at": _now()}
            )
            atomic_write_json(layout.manifest, target.model_dump(mode="json"))
            copied_files = 0
            copied_bytes = 0
            try:
                mappings: list[tuple[Path, Path]] = [
                    (paths["processed"], layout.corpus_processed),
                    (paths["analysis"], layout.analysis_summaries),
                    (paths["style"], layout.analysis_style),
                    (paths["planning"], layout.planning),
                    (paths["planning"] / "drafts", layout.draft_store / "drafts"),
                    (
                        paths["planning"] / "generations",
                        layout.draft_store / "generations",
                    ),
                    (
                        paths["planning"] / "versions",
                        layout.draft_store / "versions",
                    ),
                    (paths["planning"] / "manifest.json", layout.draft_store / "manifest.json"),
                    (paths["writing"], layout.writing),
                    (
                        paths["writing"] / "book_plan" / "longzu6_plan.json",
                        layout.writing / "book_plan" / "book_plan.json",
                    ),
                    (
                        paths["writing"] / "book_plan" / "longzu6_plan.md",
                        layout.writing / "book_plan" / "book_plan.md",
                    ),
                ]
                if request.corpus_mode == "copy":
                    mappings.append((paths["source"], layout.corpus_source))
                for source, destination in mappings:
                    count, size = self._copy_path(source, destination)
                    copied_files += count
                    copied_bytes += size
                if paths["index"].is_file():
                    count, size = self._copy_path(
                        paths["index"],
                        layout.corpus_index / "chapters_meta.json",
                    )
                    copied_files += count
                    copied_bytes += size
                for name in (
                    "import_report.json",
                    "chapter_audit_report.json",
                    "chapter_audit_report.md",
                ):
                    count, size = self._copy_path(
                        paths["reports"] / name,
                        layout.corpus_reports / name,
                    )
                    copied_files += count
                    copied_bytes += size
                self._normalize_migrated_metadata(layout, target)
                after_count, after_words = self._chapter_stats(
                    layout.corpus_index / "chapters_meta.json"
                )
                if (after_count, after_words) != (
                    preview.chapter_count,
                    preview.total_words,
                ):
                    raise RuntimeError("迁移后章节统计不一致")
                migrated = target.model_copy(
                    update={"migration_state": "complete", "updated_at": _now()}
                )
                atomic_write_json(layout.manifest, migrated.model_dump(mode="json"))
            except Exception:
                failed_root = safe_child(self.root, ".failed_migrations")
                failed_root.mkdir(parents=True, exist_ok=True)
                if layout.root.exists():
                    failed = target.model_copy(
                        update={"migration_state": "failed", "updated_at": _now()}
                    )
                    atomic_write_json(
                        layout.manifest,
                        failed.model_dump(mode="json"),
                    )
                    layout.root.replace(
                        safe_child(
                            failed_root,
                            f"{target.project_id}-{_timestamp()}-{uuid.uuid4().hex[:8]}",
                        )
                    )
                raise
            return LegacyMigrationResult(
                source_project_id=project_id,
                target_project_id=target.project_id,
                backup_path=str(backup),
                copied_files=copied_files,
                copied_bytes=copied_bytes,
                chapter_count_before=preview.chapter_count,
                chapter_count_after=after_count,
                total_words_before=preview.total_words,
                total_words_after=after_words,
            )

    def _backup_legacy(self, paths: dict[str, Path], project_id: str) -> Path:
        backup_root = safe_child(self.root, ".migration_backups")
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / f"{project_id}-pre-migration-{_timestamp()}.zip"
        temporary = backup.with_name(f".{backup.name}.{uuid.uuid4().hex}.tmp")
        sources = {
            "chapters_meta.json": paths["index"],
            "analysis": paths["analysis"],
            "style": paths["style"],
            "planning": paths["planning"],
            "writing": paths["writing"],
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for label, source in sources.items():
                if source.is_symlink():
                    continue
                if source.is_file():
                    archive.write(source, label)
                elif source.is_dir():
                    for path in source.rglob("*"):
                        if path.is_file() and not path.is_symlink():
                            archive.write(
                                path,
                                f"{label}/{path.relative_to(source).as_posix()}",
                            )
        temporary.replace(backup)
        return backup

    @staticmethod
    def _normalize_migrated_metadata(
        layout: ProjectLayout,
        project: Project,
    ) -> None:
        targets = (
            layout.writing / "manifest.json",
            layout.draft_store / "manifest.json",
            layout.planning / "outline.json",
            layout.planning / "book_plan.json",
            layout.writing / "book_plan" / "longzu6_plan.json",
            layout.writing / "book_plan" / "book_plan.json",
        )
        for path in targets:
            if not path.is_file():
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            value["project_id"] = project.project_id
            if path.name in {"manifest.json", "outline.json"}:
                value["title"] = project.title
            atomic_write_json(path, value)

    @staticmethod
    def _chapter_stats(index_path: Path) -> tuple[int, int]:
        if not index_path.is_file():
            return 0, 0
        try:
            value = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0, 0
        records = value.values() if isinstance(value, dict) else value
        if not isinstance(records, Iterable):
            return 0, 0
        items = [item for item in records if isinstance(item, dict)]
        return len(items), sum(int(item.get("word_count") or 0) for item in items)

    @staticmethod
    def _count_files(root: Path, pattern: str) -> int:
        return len(list(root.glob(pattern))) if root.is_dir() else 0

    @staticmethod
    def _measure(paths: Iterable[Path]) -> tuple[int, int]:
        count = 0
        size = 0
        for source in paths:
            if source.is_file() and not source.is_symlink():
                count += 1
                size += source.stat().st_size
            elif source.is_dir() and not source.is_symlink():
                for path in source.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        count += 1
                        size += path.stat().st_size
        return count, size

    @staticmethod
    def _copy_path(source: Path, destination: Path) -> tuple[int, int]:
        if not source.exists() or source.is_symlink():
            return 0, 0
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex}.tmp"
            )
            shutil.copy2(source, temporary)
            temporary.replace(destination)
            return 1, source.stat().st_size
        count = 0
        size = 0
        for path in source.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            target = safe_child(destination, *path.relative_to(source).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(path, temporary)
            temporary.replace(target)
            count += 1
            size += path.stat().st_size
        return count, size


project_store = ProjectStore()
