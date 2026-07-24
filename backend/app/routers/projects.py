from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    LegacyMigrationPreview,
    LegacyMigrationRequest,
    LegacyMigrationResult,
    Project,
    ProjectCreateRequest,
    ProjectDeleteResult,
    ProjectSummary,
    ProjectUpdateRequest,
)
from app.services.project_store import project_store
from app.services.project_runtime import clear_project_runtime
from app.services.project_context import use_project
from app.services.task_manager import task_manager


router = APIRouter()


def _project_or_404(project_id: str) -> Project:
    try:
        return project_store.get(project_id)
    except KeyError as exc:
        raise HTTPException(404, "项目不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("")
async def list_projects(include_archived: bool = True) -> list[Project]:
    return project_store.list_projects(include_archived=include_archived)


@router.post("", status_code=201)
async def create_project(request: ProjectCreateRequest) -> Project:
    try:
        return project_store.create(request)
    except FileExistsError as exc:
        raise HTTPException(409, "project_id 已存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{project_id}")
async def get_project(project_id: str) -> Project:
    return _project_or_404(project_id)


@router.put("/{project_id}")
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
) -> Project:
    _project_or_404(project_id)
    try:
        return project_store.update(project_id, request)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{project_id}/archive")
async def archive_project(project_id: str) -> Project:
    _project_or_404(project_id)
    try:
        return project_store.archive(project_id)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    confirm_project_id: str = Query(...),
) -> ProjectDeleteResult:
    _project_or_404(project_id)
    try:
        result = project_store.delete(project_id, confirm_project_id)
        task_manager.archive_project(project_id)
        clear_project_runtime(project_id)
        return result
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{project_id}/summary")
async def get_project_summary(project_id: str) -> ProjectSummary:
    _project_or_404(project_id)
    tasks = task_manager.list(200, project_id=project_id)
    active_tasks = len(
        [task for task in tasks if task.status.value in {"pending", "running"}]
    )
    summary = project_store.summary(project_id, active_task_count=active_tasks)

    # Runtime stores are project-scoped. Keep the dashboard summary metadata-only.
    with use_project(project_id):
        from app.routers.analysis import _style_profiles
        from app.routers.generation import get_current_knowledge_base
        from app.services.planning_store import planning_store
        from app.services.writing_project_store import writing_project_store

        profiles = list(_style_profiles.values())
        knowledge = get_current_knowledge_base()
        book_plan = writing_project_store.load_book_plan()
        plans = planning_store.list_plans()
        official_chapters = writing_project_store.list_official_chapters()

    current_plan = next(
        (plan for plan in plans if plan.status not in {"official", "archived"}),
        plans[-1] if plans else None,
    )
    planned_count = len(
        [plan for plan in plans if plan.status not in {"unplanned", "archived"}]
    )
    quality_checked_count = len(
        [plan for plan in plans if plan.status == "quality_checked"]
    )

    if summary.corpus_chapter_count == 0:
        recommended_step, recommended_action = "import_corpus", "导入并扫描语料"
    elif not profiles:
        recommended_step, recommended_action = "analyze", "开始作品分析"
    elif book_plan is None:
        recommended_step, recommended_action = "conceive", "自动构想下一部"
    elif not book_plan.accepted:
        recommended_step, recommended_action = "review_concept", "审核并接受总体构想"
    elif not book_plan.chapter_plans_complete:
        recommended_step, recommended_action = "complete_plans", "生成完整章节规划"
    elif current_plan and current_plan.status in {"unplanned", "planned"}:
        recommended_step, recommended_action = "generate", "生成本章完整草稿"
    elif current_plan and current_plan.status == "draft_review":
        recommended_step, recommended_action = "review_draft", "审核并修改当前草稿"
    elif current_plan and current_plan.status == "quality_checked":
        recommended_step, recommended_action = "save_official", "确认保存正式章节"
    else:
        recommended_step, recommended_action = "export", "查看版本与导出"

    recent_tasks = [
        {
            "task_id": task.task_id,
            "title": task.user_visible_title,
            "status": task.status.value,
            "progress": task.progress,
            "stage": task.stage,
            "updated_at": task.updated_at.isoformat(),
        }
        for task in tasks[:5]
    ]
    recent_official = [
        {
            "chapter_id": chapter.chapter_id,
            "order": chapter.order,
            "title": chapter.title,
            "word_count": chapter.word_count,
            "updated_at": chapter.updated_at.isoformat(),
        }
        for chapter in reversed(official_chapters[-5:])
    ]
    knowledge_ready = bool(
        knowledge.characters
        or knowledge.world_settings
        or knowledge.plot_nodes
        or knowledge.themes
    )

    return summary.model_copy(
        update={
            "analysis_profile_count": len(profiles),
            "knowledge_ready": knowledge_ready,
            "book_plan_exists": book_plan is not None,
            "book_plan_accepted": bool(book_plan and book_plan.accepted),
            "chapter_plans_complete": bool(
                book_plan and book_plan.chapter_plans_complete
            ),
            "chapter_plan_count": len(plans),
            "planned_chapter_count": planned_count,
            "quality_checked_count": quality_checked_count,
            "current_chapter_order": current_plan.order if current_plan else None,
            "current_chapter_title": current_plan.title if current_plan else "",
            "current_chapter_status": current_plan.status if current_plan else "",
            "recent_tasks": recent_tasks,
            "recent_official_chapters": recent_official,
            "recommended_step": recommended_step,
            "recommended_action": recommended_action,
        }
    )


@router.get("/{project_id}/migration-preview")
async def get_migration_preview(project_id: str) -> LegacyMigrationPreview:
    _project_or_404(project_id)
    try:
        return project_store.migration_preview(project_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{project_id}/migrate", status_code=201)
async def migrate_legacy_project(
    project_id: str,
    request: LegacyMigrationRequest,
) -> LegacyMigrationResult:
    _project_or_404(project_id)
    try:
        return project_store.migrate_legacy(project_id, request)
    except FileExistsError as exc:
        raise HTTPException(409, "迁移目标 project_id 已存在") from exc
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
