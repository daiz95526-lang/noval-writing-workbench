from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from app.models.schemas import (
    AIChapterRepairRequest,
    AIChapterReviewRequest,
    AIChapterReviewResult,
    DraftExportRequest,
    ChapterCompletenessRequest,
    ChapterCompletenessResult,
    GenerationRequest,
    GenerationResult,
    IterateRequest,
    LongTask,
    OfficialChapter,
    OfficialChapterSaveRequest,
    OfficialChapterUpdateRequest,
    TempGeneration,
    TempGenerationCreate,
    TaskType,
    WritingProjectManifest,
)
from app.services.planning_store import planning_store
from app.services.project_context import get_current_project_id, run_in_project
from app.services.task_manager import task_manager
from app.services.writing_project_store import writing_project_store


router = APIRouter()


def _completeness_has_blockers(check: dict) -> bool:
    word_count = int(check.get("word_count") or 0)
    maximum = int(check.get("maximum_word_count") or 0)

    def blocks(issue) -> bool:
        if not isinstance(issue, dict):
            return False
        code = str(issue.get("code") or "")
        if code in {
            "chapter_too_long",
            "chapter_above_recommended",
            "chapter_strongly_above_recommended",
        }:
            return bool(maximum and word_count > maximum * 2)
        if code in {"chapter_too_short", "chapter_below_recommended"}:
            return word_count < 500
        if code in {
            "summary_alignment",
            "ending_state",
            "next_bridge",
            "plot_beat_coverage",
            "duplicate_paragraphs",
        }:
            return False
        return issue.get("level") == "error"

    if "blocking_errors" in check:
        return any(blocks(issue) for issue in check.get("blocking_errors") or [])
    issues = check.get("issues") or []
    if issues:
        return any(blocks(issue) for issue in issues)
    return not bool(check.get("passed", False))


@router.get("/writing-project")
async def get_writing_project() -> WritingProjectManifest:
    return writing_project_store.get_manifest()


@router.post("/chapter-generation/start")
async def start_chapter_generation(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    await _validate_chapter_generation(request)
    from app.routers.tasks import start_generation

    request.append_to_draft = False
    return await start_generation(request, background_tasks)


@router.post("/chapter-generation/full-chapter/start")
async def start_full_chapter_generation(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    chapter_plan = await _validate_chapter_generation(request)
    request.generation_kind = "full_chapter"
    request.append_to_draft = False
    if request.target_word_count < 1200:
        request.target_word_count = chapter_plan.target_words
    from app.routers.tasks import start_generation

    return await start_generation(request, background_tasks)


@router.post("/chapter-generation/check-completeness")
async def check_generation_completeness(
    request: ChapterCompletenessRequest,
) -> ChapterCompletenessResult:
    from app.services.chapter_quality import check_chapter_completeness

    try:
        plan = planning_store.get_plan(request.plan_id)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    return check_chapter_completeness(request.content, plan)


@router.post("/chapter-generation/ai-review/start")
async def start_ai_chapter_review(
    request: AIChapterReviewRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    try:
        plan = planning_store.get_plan(request.plan_id)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    task = task_manager.create(
        TaskType.CHAPTER_REVIEW,
        {
            "generation_id": request.generation_id,
            "plan_id": plan.plan_id,
            "chapter_order": plan.order,
            "content_chars": len(request.content),
        },
        target_id=plan.plan_id,
        user_visible_title=f"质检第 {plan.order} 章",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_ai_chapter_review,
        task.task_id,
        request,
    )
    return task


@router.post("/chapter-generation/ai-repair/start")
async def start_ai_chapter_repair(
    request: AIChapterRepairRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    try:
        plan = planning_store.get_plan(request.plan_id)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    task = task_manager.create(
        TaskType.CHAPTER_REPAIR,
        {
            "generation_id": request.generation_id,
            "plan_id": plan.plan_id,
            "chapter_order": plan.order,
            "review_score": request.review_report.score,
        },
        target_id=plan.plan_id,
        user_visible_title=f"修复第 {plan.order} 章",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_ai_chapter_repair,
        task.task_id,
        request,
    )
    return task


@router.get("/chapter-generation/{task_id}")
async def get_chapter_generation(task_id: str) -> LongTask:
    task = task_manager.get(task_id, project_id=get_current_project_id())
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/chapter-generation/revise")
async def revise_chapter_generation(
    request: IterateRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.tasks import start_revision

    return await start_revision(request, background_tasks)


@router.post("/chapter-generation/save-temp")
async def save_temp_generation(request: TempGenerationCreate) -> TempGeneration:
    return writing_project_store.create_temp_generation(request)


@router.post("/chapter-generation/save-official")
async def save_official_chapter(
    request: OfficialChapterSaveRequest,
) -> OfficialChapter:
    if request.source_temp_id:
        try:
            temp = writing_project_store.get_temp_generation(request.source_temp_id)
        except KeyError:
            temp = None
        if temp:
            saved_check = temp.generation_request.get("_completeness_check")
            effective_check = (
                request.completeness_check
                if request.completeness_check
                else saved_check
            )
            if isinstance(effective_check, dict):
                blocked = _completeness_has_blockers(effective_check)
                if blocked:
                    raise HTTPException(
                        409,
                        "章节存在阻断性问题，请先修复正文为空、极短、乱码或严重断句等问题",
                    )
            if not request.completeness_check and isinstance(saved_check, dict):
                request.completeness_check = saved_check
            saved_plan = temp.generation_request.get("_chapter_plan_snapshot")
            if not request.chapter_plan_snapshot and isinstance(saved_plan, dict):
                request.chapter_plan_snapshot = saved_plan
    try:
        chapter = writing_project_store.save_official_chapter(request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if request.source_plan_id:
        try:
            planning_store.update_plan_status(request.source_plan_id, "official")
        except KeyError:
            pass
    return chapter


@router.get("/temp-generations")
async def list_temp_generations() -> list[TempGeneration]:
    return writing_project_store.list_temp_generations()


@router.get("/temp-generations/page")
async def list_temp_generations_page(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    records = writing_project_store.list_temp_generations()
    total = len(records)
    items = [
        record.model_dump(
            mode="json",
            exclude={"content", "generation_request"},
        )
        for record in records[offset : offset + limit]
    ]
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/temp-generations/{temp_id}")
async def get_temp_generation(temp_id: str) -> TempGeneration:
    try:
        return writing_project_store.get_temp_generation(temp_id)
    except KeyError as exc:
        raise HTTPException(404, "临时生成记录不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/temp-generations/{temp_id}")
async def delete_temp_generation(temp_id: str) -> dict[str, str]:
    try:
        if not writing_project_store.delete_temp_generation(temp_id):
            raise HTTPException(404, "临时生成记录不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": temp_id}


@router.post("/temp-generations/{temp_id}/load-to-editor")
async def load_temp_to_editor(temp_id: str) -> TempGeneration:
    from app.routers import generation

    try:
        record = writing_project_store.get_temp_generation(temp_id)
    except KeyError as exc:
        raise HTTPException(404, "临时生成记录不存在") from exc
    request = _generation_request_from_record(record)
    generation._generation_results[record.generation_id] = GenerationResult(
        id=record.generation_id,
        request=request,
        content=record.content,
        suggested_title=record.chapter_title,
        generation_file_path=record.file_path,
        save_status="temporary",
        accepted=record.accepted,
    )
    return record


@router.get("/official-chapters")
async def list_official_chapters() -> list[OfficialChapter]:
    return writing_project_store.list_official_chapters()


@router.get("/official-chapters/page")
async def list_official_chapters_page(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    chapters = writing_project_store.list_official_chapters()
    total = len(chapters)
    items = [
        chapter.model_dump(
            mode="json",
            exclude={"content", "chapter_plan_snapshot"},
        )
        for chapter in chapters[offset : offset + limit]
    ]
    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/official-chapters/{chapter_id}")
async def get_official_chapter(chapter_id: str) -> OfficialChapter:
    try:
        return writing_project_store.get_official_chapter(chapter_id)
    except KeyError as exc:
        raise HTTPException(404, "正式章节不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/official-chapters/{chapter_id}")
async def update_official_chapter(
    chapter_id: str,
    request: OfficialChapterUpdateRequest,
) -> OfficialChapter:
    try:
        return writing_project_store.update_official_chapter(chapter_id, request)
    except KeyError as exc:
        raise HTTPException(404, "正式章节不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/official-chapters/{chapter_id}")
async def delete_official_chapter(chapter_id: str) -> dict[str, str]:
    try:
        if not writing_project_store.delete_official_chapter(chapter_id):
            raise HTTPException(404, "正式章节不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": chapter_id}


@router.post("/official-chapters/{chapter_id}/export")
async def export_official_chapter(
    chapter_id: str,
    request: DraftExportRequest,
) -> FileResponse:
    try:
        path = writing_project_store.export_official_chapter(
            chapter_id,
            request.format,
        )
    except KeyError as exc:
        raise HTTPException(404, "正式章节不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(
        path,
        media_type="text/markdown" if request.format == "md" else "text/plain",
        filename=path.name,
    )


@router.post("/official-chapters/{chapter_id}/load-to-editor")
async def load_official_to_editor(chapter_id: str) -> TempGeneration:
    from app.routers import generation

    try:
        record = writing_project_store.create_editor_record_from_official(
            chapter_id
        )
    except KeyError as exc:
        raise HTTPException(404, "正式章节不存在") from exc
    request = _generation_request_from_record(record)
    generation._generation_results[record.generation_id] = GenerationResult(
        id=record.generation_id,
        request=request,
        content=record.content,
        suggested_title=record.chapter_title,
        generation_file_path=record.file_path,
        save_status="temporary",
    )
    return record


def _generation_request_from_record(record: TempGeneration) -> GenerationRequest:
    payload = dict(record.generation_request)
    plan = None
    if record.source_plan_id:
        try:
            plan = planning_store.get_plan(record.source_plan_id)
        except KeyError:
            plan = None
    anchor = str(
        payload.get("start_chapter_id")
        or payload.get("source_anchor_chapter_id")
        or (plan.anchor_chapter_id if plan else "")
    )
    if not anchor:
        raise HTTPException(
            409,
            "该记录缺少原文锚点，无法继续调用模型修改，但仍可手工编辑",
        )
    return GenerationRequest(
        start_chapter_id=anchor,
        source_anchor_chapter_id=anchor,
        plot_direction=str(payload.get("plot_direction") or ""),
        target_word_count=max(
            300,
            min(8000, int(payload.get("target_word_count") or max(300, record.word_count))),
        ),
        mode=payload.get("mode") or "chapter",
        draft_id=str(payload.get("draft_id") or (plan.draft_id if plan else "")),
        plan_id=record.source_plan_id,
        append_to_draft=False,
        reference_chapter_ids=payload.get("reference_chapter_ids") or [],
        pov_character=str(payload.get("pov_character") or ""),
        additional_instructions=str(payload.get("additional_instructions") or ""),
        generation_kind="revision",
    )


async def _validate_chapter_generation(
    request: GenerationRequest,
):
    from app.services.chapter_planner import book_plan_chapters_complete

    book_plan = writing_project_store.load_book_plan()
    if book_plan is None or not book_plan.accepted:
        raise HTTPException(409, "请先接受总体构想，再生成章节")
    if not book_plan_chapters_complete(book_plan):
        raise HTTPException(409, "章节规划未完成，不能开始正式正文生成")
    if not request.plan_id:
        raise HTTPException(400, "章节生成必须绑定总体构想中的章节规划")
    try:
        chapter_plan = planning_store.get_plan(request.plan_id)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    if chapter_plan.book_plan_id != book_plan.book_plan_id:
        raise HTTPException(409, "章节规划不属于当前已接受的总体构想")
    return chapter_plan


def _chapter_review_context(plan):
    from app.routers import generation

    previous = (
        writing_project_store.get_official_chapter_by_order(plan.order - 1)
        if plan.order > 1
        else None
    )
    next_plan = next(
        (
            item
            for item in planning_store.list_plans()
            if item.book_plan_id == plan.book_plan_id
            and item.order == plan.order + 1
        ),
        None,
    )
    return (
        writing_project_store.load_book_plan(),
        previous.content[-2000:] if previous else "",
        next_plan,
        generation.get_current_knowledge_base(),
    )


def _review_progress(task_id: str):
    from app.models.schemas import LongTaskStatus

    def report(progress: float, stage: str, message: str) -> None:
        task_manager.update(
            task_id,
            status=LongTaskStatus.RUNNING,
            progress=progress,
            stage=stage,
            message=message,
            log=message,
        )

    return report


async def _run_ai_chapter_review(
    task_id: str,
    request: AIChapterReviewRequest,
) -> None:
    from app.services.chapter_quality import check_chapter_completeness
    from app.services.chapter_reviewer import ChapterReviewService
    from app.services.task_manager import TaskCancelled

    try:
        plan = planning_store.get_plan(request.plan_id)
        book_plan, previous_tail, next_plan, knowledge_base = _chapter_review_context(plan)
        rule_check = check_chapter_completeness(request.content, plan)
        review = await ChapterReviewService().review(
            generation_id=request.generation_id,
            content=request.content,
            plan=plan,
            book_plan=book_plan,
            previous_chapter_tail=previous_tail,
            next_plan=next_plan,
            knowledge_base=knowledge_base,
            rule_check=rule_check,
            progress_callback=_review_progress(task_id),
        )
        if request.generation_id:
            writing_project_store.attach_generation_metadata(
                request.generation_id,
                "_ai_review",
                review.model_dump(mode="json"),
            )
        review_payload = review.model_dump(mode="json")
        result = {
            "ai_review": review_payload,
            "structured_report": (
                review_payload if review.report_format == "structured" else None
            ),
            "readable_report": review.readable_report,
            "raw_response": review.raw_response,
            "parse_warning": review.parse_warning,
            "completeness_check": rule_check.model_dump(mode="json"),
        }
        if review.report_format == "text" or review.parse_warning:
            planning_store.update_plan_status(request.plan_id, "quality_checked")
            task_manager.partial_succeed(
                task_id,
                result,
                "AI 深度质检完成，但报告为非结构化文本",
            )
        else:
            planning_store.update_plan_status(request.plan_id, "quality_checked")
            task_manager.succeed(
                task_id,
                result,
                f"AI 深度质检完成，评分 {review.score}",
            )
    except TaskCancelled:
        return
    except Exception as exc:
        task_manager.fail(task_id, exc)


async def _run_ai_chapter_repair(
    task_id: str,
    request: AIChapterRepairRequest,
) -> None:
    from app.routers import generation
    from app.models.schemas import GenerationRequest
    from app.services.chapter_quality import check_chapter_completeness
    from app.services.chapter_reviewer import ChapterReviewService
    from app.services.draft_store import draft_store
    from app.services.task_manager import TaskCancelled

    try:
        plan = planning_store.get_plan(request.plan_id)
        book_plan, previous_tail, next_plan, knowledge_base = _chapter_review_context(plan)
        repaired = await ChapterReviewService().repair(
            content=request.content,
            plan=plan,
            review=request.review_report,
            previous_chapter_tail=previous_tail,
            next_plan=next_plan,
            book_plan=book_plan,
            knowledge_base=knowledge_base,
            progress_callback=_review_progress(task_id),
        )
        completeness = check_chapter_completeness(repaired, plan)
        generation_request = GenerationRequest(
            start_chapter_id=plan.anchor_chapter_id,
            source_anchor_chapter_id=plan.anchor_chapter_id,
            target_word_count=plan.target_words,
            mode="chapter",
            draft_id=plan.draft_id,
            plan_id=plan.plan_id,
            append_to_draft=False,
            generation_kind="revision",
        )
        result = GenerationResult(
            id=task_id,
            request=generation_request,
            content=repaired,
            suggested_title=plan.title,
        )
        temp_record = writing_project_store.save_generation_result(
            result,
            record_type="ai_repair",
            chapter_order=plan.order,
            chapter_title=plan.title,
            completeness_check=completeness.model_dump(mode="json"),
            chapter_plan_snapshot=plan.model_dump(mode="json"),
        )
        writing_project_store.attach_generation_metadata(
            result.id,
            "_source_ai_review",
            request.review_report.model_dump(mode="json"),
        )
        result.generation_file_path = temp_record.file_path
        generation._generation_results[result.id] = result
        draft_store.save_generation(result.id, result.model_dump(mode="json"))
        task_manager.succeed(
            task_id,
            {
                "generation_result": result.model_dump(mode="json"),
                "temp_generation": temp_record.model_dump(mode="json"),
                "completeness_check": completeness.model_dump(mode="json"),
                "source_ai_review": request.review_report.model_dump(mode="json"),
            },
            "AI 修复候选版本已生成，请审核后决定是否采用",
        )
    except TaskCancelled:
        return
    except Exception as exc:
        task_manager.fail(
            task_id,
            exc,
            result={
                "original_content": request.content,
                "source_ai_review": request.review_report.model_dump(mode="json"),
            },
        )
