"""Import the active project's local corpus."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import settings
from app.models.schemas import (
    Chapter,
    ChapterMeta,
    ImportDetail,
    ImportReport,
)
from app.services.file_ops import atomic_write_json, atomic_write_text
from app.services.preprocessor import TextPreprocessor
from app.services.project_paths import RuntimeProjectPaths, get_project_paths

_BOOK_DIR = settings.data_dir / "books" / "longzu"
_SOURCE_DIR = _BOOK_DIR / "source_txt"
_META_INDEX_PATH = settings.data_dir / "chapters_meta.json"
_IMPORT_REPORT_PATH = _BOOK_DIR / "import_report.json"


def _runtime_paths() -> RuntimeProjectPaths:
    paths = get_project_paths()
    if not paths.legacy:
        return paths
    return RuntimeProjectPaths(
        **{
            **paths.__dict__,
            "source": _SOURCE_DIR,
            "index": _META_INDEX_PATH,
            "reports": _IMPORT_REPORT_PATH.parent,
        }
    )


def read_text_with_encoding(file_path: Path) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16"):
        try:
            return file_path.read_text(encoding=encoding), encoding
        except UnicodeError:
            continue
    raise UnicodeError("无法识别文件编码（已尝试 utf-8/gb18030/gbk/utf-16）")


def chapter_sort_key(chapter: Chapter | ChapterMeta) -> tuple[int, str, int]:
    return (
        chapter.series_order,
        chapter.sub_order or "",
        chapter.chapter_order,
    )


class LocalImporter:
    """Build one deterministic corpus from the eight canonical source files."""

    def __init__(self) -> None:
        self._preprocessor = TextPreprocessor()
        self._report: ImportReport | None = None

    @property
    def last_report(self) -> ImportReport | None:
        if self._report is not None:
            return self._report
        report_path = _runtime_paths().reports / "import_report.json"
        if not report_path.exists():
            return None
        try:
            self._report = ImportReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        return self._report

    def scan_and_import(self) -> ImportReport:
        from app.routers.corpus import _corpus_store

        paths = _runtime_paths()
        files = sorted(paths.source.glob("*.txt")) if paths.source.exists() else []
        report = ImportReport(scanned_files=len(files))
        candidate_store: dict[str, Chapter] = {}
        seen_hashes: set[str] = set()
        previous_hashes = {
            chapter.content_hash
            for chapter in _corpus_store.values()
            if chapter.content_hash
        }

        for file_path in files:
            detail = ImportDetail(file=file_path.name)
            report.details.append(detail)
            try:
                raw_text, _encoding = read_text_with_encoding(file_path)
                if not raw_text.strip():
                    detail.status = "empty"
                    continue

                chapters = self._preprocessor.process(raw_text, file_path.stem)
                detail.chapters_found = len(chapters)
                for chapter in chapters:
                    if chapter.content_hash in seen_hashes:
                        detail.chapters_skipped += 1
                        report.skipped_duplicates += 1
                        continue
                    if chapter.chapter_id in candidate_store:
                        raise ValueError(f"章节 ID 冲突: {chapter.chapter_id}")
                    candidate_store[chapter.chapter_id] = chapter
                    seen_hashes.add(chapter.content_hash)
                    if chapter.content_hash not in previous_hashes:
                        detail.chapters_added += 1
                        report.new_chapters += 1
            except Exception as exc:
                detail.status = "error"
                detail.error_message = str(exc)
                report.failed_files += 1

        if not files:
            report.failed_files = 1
            report.details.append(
                ImportDetail(
                    file=str(paths.source),
                    status="error",
                    error_message="主语料目录不存在或没有 txt 文件",
                )
            )

        if report.failed_files:
            report.total_chapters_after = len(_corpus_store)
            self._persist_report(report)
            return report

        paths.processed.mkdir(parents=True, exist_ok=True)
        for path in paths.processed.glob("*.txt"):
            path.unlink()

        _corpus_store.clear()
        for chapter in sorted(candidate_store.values(), key=chapter_sort_key):
            _corpus_store[chapter.chapter_id] = chapter
            atomic_write_text(
                paths.processed / f"{chapter.chapter_id}.txt",
                chapter.content,
            )

        _save_meta_index(_corpus_store)
        report.total_chapters_after = len(_corpus_store)
        self._persist_report(report)

        from app.services.chapter_audit import generate_chapter_audit

        generate_chapter_audit(
            source_dir=paths.source,
            imported_chapters=list(_corpus_store.values()),
            output_dir=paths.reports,
        )
        return report

    def _persist_report(self, report: ImportReport) -> None:
        self._report = report
        report_path = _runtime_paths().reports / "import_report.json"
        atomic_write_text(
            report_path,
            report.model_dump_json(indent=2),
        )


def _save_meta_index(corpus_store: dict[str, Chapter]) -> None:
    index = {
        chapter_id: ChapterMeta.model_validate(chapter).model_dump(mode="json")
        for chapter_id, chapter in corpus_store.items()
    }
    atomic_write_json(_runtime_paths().index, index)


def save_meta_index(corpus_store: dict[str, Chapter]) -> None:
    _save_meta_index(corpus_store)


def load_meta_index() -> dict[str, ChapterMeta]:
    index_path = _runtime_paths().index
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    result: dict[str, ChapterMeta] = {}
    for chapter_id, item in data.items():
        try:
            result[chapter_id] = ChapterMeta(
                chapter_id=item.get("chapter_id") or chapter_id,
                series_order=int(item.get("series_order", 0)),
                sub_order=item.get("sub_order") or None,
                volume_key=item.get("volume_key") or item.get("volume", ""),
                volume_display_name=item.get("volume_display_name", ""),
                chapter_order=int(
                    item.get("chapter_order", item.get("chapter_index", 0))
                ),
                title=item.get("title") or chapter_id,
                word_count=int(item.get("word_count", 0)),
                dialogue_ratio=float(item.get("dialogue_ratio", 0.0)),
                source_file=item.get("source_file", ""),
                content_hash=item.get("content_hash", ""),
            )
        except (TypeError, ValueError):
            continue
    return result


_importer: LocalImporter | None = None


def get_importer() -> LocalImporter:
    global _importer
    if _importer is None:
        _importer = LocalImporter()
    return _importer


def scan_and_import() -> ImportReport:
    return get_importer().scan_and_import()


def get_last_import_report() -> ImportReport | None:
    return get_importer().last_report
