import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.config import settings
from app.models.schemas import (
    AnalysisDimension,
    AnalysisStatus,
    DimensionResult,
    StyleProfile,
    TaskStatus,
)

router = APIRouter()

_style_profiles: dict[str, StyleProfile] = {}
_tasks: dict[str, TaskStatus] = {}


@router.get("/profiles")
async def list_profiles() -> list[StyleProfile]:
    return list(_style_profiles.values())


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str) -> StyleProfile:
    if profile_id not in _style_profiles:
        raise HTTPException(404, "分析结果不存在")
    return _style_profiles[profile_id]


@router.post("/analyze/{chapter_id}")
async def start_analysis(chapter_id: str, background_tasks: BackgroundTasks) -> TaskStatus:
    from app.routers.corpus import _corpus_store

    if chapter_id not in _corpus_store:
        raise HTTPException(404, "章节不存在")
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = TaskStatus(task_id=task_id, status=AnalysisStatus.PENDING)
    background_tasks.add_task(_run_analysis, task_id, chapter_id)
    return _tasks[task_id]


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> TaskStatus:
    if task_id not in _tasks:
        raise HTTPException(404, "任务不存在")
    return _tasks[task_id]


async def _run_analysis(task_id: str, chapter_id: str):
    _tasks[task_id].status = AnalysisStatus.RUNNING
    _tasks[task_id].progress = 0.1
    try:
        from app.routers.corpus import _corpus_store
        from app.services.style_analyzer import analyze_chapter

        chapter = _corpus_store.get(chapter_id)
        if not chapter:
            _tasks[task_id].status = AnalysisStatus.ERROR
            _tasks[task_id].message = "章节不存在"
            return

        result = await analyze_chapter(chapter)
        if not result or not any(item.summary.strip() for item in result):
            raise ValueError("分析结果为空")
        profile = StyleProfile(
            id=str(uuid.uuid4())[:8],
            chapter_ids=[chapter_id],
            dimensions=result,
            global_summary="；".join(
                item.summary for item in result[:3] if item.summary
            ),
        )
        _style_profiles[profile.id] = profile

        _tasks[task_id].status = AnalysisStatus.COMPLETED
        _tasks[task_id].progress = 1.0
        _tasks[task_id].message = profile.id
    except Exception as e:
        _tasks[task_id].status = AnalysisStatus.ERROR
        _tasks[task_id].message = str(e)
