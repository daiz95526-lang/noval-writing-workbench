import hashlib
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from app.models.schemas import Chapter, CorpusStats, CorpusStatus, ChapterMeta, ImportReport
from app.services.file_ops import atomic_write_text
from app.services.project_context import ProjectScopedDict, get_current_project_id
from app.services.project_paths import get_project_paths

router = APIRouter()

_corpus_store: ProjectScopedDict[Chapter] = ProjectScopedDict({})
_loaded_projects: set[str] = set()


def _chapter_path(chapter_id: str) -> Path:
    return get_project_paths().processed / f"{chapter_id}.txt"


def _scan_processed():
    """从 processed/ 目录和元数据索引恢复章节数据"""
    from app.services.local_importer import load_meta_index

    paths = get_project_paths()
    paths.processed.mkdir(parents=True, exist_ok=True)

    meta_index = load_meta_index()

    for f in sorted(paths.processed.glob("*.txt")):
        cid = f.stem
        if cid in _corpus_store:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue

        if cid in meta_index:
            meta = meta_index[cid]
        else:
            # 回退：从文件名和内容推断
            meta = ChapterMeta(
                chapter_id=cid,
                series_order=999,
                volume_key=cid.rsplit("-", 1)[0] if "-" in cid else "legacy",
                volume_display_name="历史导入",
                chapter_order=0,
                title=cid,
                word_count=len(re.sub(r"\s+", "", content)),
                source_file="",
                content_hash=hashlib.sha256(
                    re.sub(r"\s+", "", content).encode("utf-8")
                ).hexdigest(),
            )

        _corpus_store[cid] = Chapter(
            **meta.model_dump(),
            content=content,
            status=CorpusStatus.PROCESSED,
        )
    _loaded_projects.add(get_current_project_id())


def _ensure_loaded() -> None:
    if get_current_project_id() not in _loaded_projects:
        _scan_processed()


_scan_processed()


@router.get("/stats")
async def get_stats() -> CorpusStats:
    _ensure_loaded()
    stats = CorpusStats()
    for ch in _corpus_store.values():
        stats.total_chapters += 1
        stats.total_words += ch.word_count
        if ch.status == CorpusStatus.PROCESSED:
            stats.processed_chapters += 1
    stats.total_volumes = len(
        {chapter.volume_key for chapter in _corpus_store.values() if chapter.volume_key}
    )
    return stats


@router.get("/chapters")
async def list_chapters(volume: str = "") -> list[ChapterMeta]:
    _ensure_loaded()
    chapters = []
    for ch in sorted(
        _corpus_store.values(),
        key=lambda c: (c.series_order, c.sub_order or "", c.chapter_order),
    ):
        if volume and ch.volume_key != volume:
            continue
        chapters.append(ChapterMeta.model_validate(ch))
    return chapters


@router.get("/chapters/{chapter_id}")
async def get_chapter(chapter_id: str) -> Chapter:
    _ensure_loaded()
    if chapter_id not in _corpus_store:
        raise HTTPException(404, "章节不存在")
    return _corpus_store[chapter_id]


@router.post("/chapters/upload")
async def upload_chapter(file: UploadFile = File(...)):
    _ensure_loaded()
    raw = await file.read()
    content = ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    if not content.strip():
        raise HTTPException(400, "文件为空或编码无法识别")

    normalized = re.sub(r"\s+", "", content)
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    cid = f"manual-{content_hash[:16]}"
    manual_order = 1 + max(
        (chapter.chapter_order for chapter in _corpus_store.values()
         if chapter.volume_key == "manual"),
        default=0,
    )
    chapter = Chapter(
        chapter_id=cid,
        series_order=999,
        volume_key="manual",
        volume_display_name="手动上传",
        chapter_order=manual_order,
        title=Path(file.filename or cid).stem,
        word_count=len(normalized),
        dialogue_ratio=0.0,
        source_file=f"manual/{file.filename or cid}",
        content_hash=content_hash,
        content=content,
        status=CorpusStatus.PROCESSED,
    )
    _corpus_store[cid] = chapter
    atomic_write_text(_chapter_path(cid), content)
    from app.services.local_importer import save_meta_index
    save_meta_index(_corpus_store)
    return {"chapter_id": cid, "word_count": chapter.word_count}


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: str):
    _ensure_loaded()
    if chapter_id not in _corpus_store:
        raise HTTPException(404, "章节不存在")
    del _corpus_store[chapter_id]
    path = _chapter_path(chapter_id)
    if path.exists():
        path.unlink()
    from app.services.local_importer import save_meta_index
    save_meta_index(_corpus_store)
    return {"deleted": chapter_id}


@router.post("/scan-local")
async def scan_local() -> ImportReport:
    """扫描当前项目配置的只读语料目录。"""
    from app.services.local_importer import scan_and_import
    report = scan_and_import()
    if report.failed_files:
        raise HTTPException(
            500,
            f"本地语料导入失败：{report.failed_files} 个文件处理失败",
        )
    return report


@router.get("/import-report")
async def get_import_report() -> ImportReport | None:
    """获取最近一次导入报告"""
    from app.services.local_importer import get_last_import_report
    return get_last_import_report()
