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
        clear_project_runtime(project_id)
        return result
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{project_id}/summary")
async def get_project_summary(project_id: str) -> ProjectSummary:
    _project_or_404(project_id)
    active_tasks = len(
        [
            task
            for task in task_manager.list(200, project_id=project_id)
            if task.status.value in {"pending", "running"}
        ]
    )
    return project_store.summary(project_id, active_task_count=active_tasks)


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
