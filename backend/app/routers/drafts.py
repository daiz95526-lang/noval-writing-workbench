from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.schemas import (
    DraftAppendRequest,
    DraftCreateRequest,
    DraftDetail,
    DraftExportRequest,
    DraftMeta,
    DraftUpdateRequest,
    DraftVersion,
    ContinuityCheckResult,
)
from app.services.draft_store import draft_store


router = APIRouter()


def _not_found(exc: KeyError) -> HTTPException:
    return HTTPException(404, f"草稿不存在: {exc.args[0]}")


@router.get("")
async def list_drafts() -> list[DraftMeta]:
    return draft_store.list_drafts()


@router.post("")
async def create_draft(request: DraftCreateRequest) -> DraftDetail:
    from app.routers.corpus import _corpus_store

    if request.source_anchor_chapter_id not in _corpus_store:
        raise HTTPException(404, "起始章节不存在")
    return draft_store.create_draft(
        title=request.title,
        source_anchor_chapter_id=request.source_anchor_chapter_id,
        notes=request.notes,
    )


@router.get("/{draft_id}")
async def get_draft(draft_id: str) -> DraftDetail:
    try:
        return draft_store.get_draft(draft_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/{draft_id}")
async def update_draft(
    draft_id: str,
    request: DraftUpdateRequest,
) -> DraftDetail:
    try:
        return draft_store.save_draft(
            draft_id,
            title=request.title,
            content=request.content,
            notes=request.notes,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{draft_id}/append")
async def append_draft(
    draft_id: str,
    request: DraftAppendRequest,
) -> DraftDetail:
    try:
        result = draft_store.append_to_draft(draft_id, request.generated_text)
        if request.generation_id:
            draft_store.update_generation(
                request.generation_id,
                accepted=True,
                saved_draft_id=draft_id,
                saved_draft_path=result.file_path,
                save_status="accepted",
            )
            try:
                from app.routers.generation import _generation_results

                if request.generation_id in _generation_results:
                    generation = _generation_results[request.generation_id]
                    generation.accepted = True
                    generation.saved_draft_id = draft_id
                    generation.saved_draft_path = result.file_path
                    generation.save_status = "accepted"
            except ImportError:
                pass
        return result
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{draft_id}/version")
async def create_version(draft_id: str) -> DraftVersion:
    try:
        return draft_store.create_version(draft_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{draft_id}/versions")
async def list_versions(draft_id: str) -> list[DraftVersion]:
    try:
        return draft_store.list_versions(draft_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{draft_id}/export")
async def export_draft(
    draft_id: str,
    request: DraftExportRequest,
) -> FileResponse:
    try:
        path = draft_store.export_draft(draft_id, request.format)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    media_type = "text/markdown" if request.format == "md" else "text/plain"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
    )


@router.post("/{draft_id}/continuity-check")
async def check_draft_continuity(draft_id: str) -> ContinuityCheckResult:
    try:
        return draft_store.check_continuity(draft_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
