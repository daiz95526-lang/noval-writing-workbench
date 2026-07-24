from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.config import settings
from app.models.schemas import (
    BookPlan,
    BookPlanGenerateRequest,
    BookPlanRevisionRequest,
    BookPlanUpdate,
    ChapterPlan,
    ChapterPlanInput,
    LongTask,
    LongTaskStatus,
    ProjectOutline,
    ProjectOutlineUpdate,
    TaskType,
)
from app.services.draft_store import draft_store
from app.services.planning_store import planning_store
from app.services.task_manager import task_manager
from app.services.writing_project_store import writing_project_store
from app.services.project_context import run_in_project


router = APIRouter()


def _report_book_plan(task_id: str):
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


def _validate_plan_links(value: ChapterPlanInput) -> None:
    from app.routers.corpus import _corpus_store

    if value.anchor_chapter_id not in _corpus_store:
        raise HTTPException(404, "章节规划的原文锚点不存在")
    if value.draft_id:
        try:
            draft_store.get_draft(value.draft_id)
        except KeyError as exc:
            raise HTTPException(404, "章节规划绑定的草稿不存在") from exc


@router.get("/outline")
async def get_outline() -> ProjectOutline:
    return planning_store.get_outline()


@router.put("/outline")
async def update_outline(request: ProjectOutlineUpdate) -> ProjectOutline:
    return planning_store.save_outline(request)


@router.get("/book-plan")
async def get_book_plan() -> BookPlan | None:
    return writing_project_store.load_book_plan() or planning_store.get_book_plan()


@router.post("/book-plan/generate")
async def generate_book_plan(
    request: BookPlanGenerateRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.corpus import _corpus_store

    if request.source_anchor_chapter_id not in _corpus_store:
        raise HTTPException(404, "自动构想的原文锚点章节不存在")
    task = task_manager.create(
        TaskType.BOOK_PLAN,
        {
            "source_anchor_chapter_id": request.source_anchor_chapter_id,
            "target_scale": request.target_scale,
            "target_chapter_count": request.target_chapter_count,
            "automation_level": request.automation_level,
        },
        operation_type="book_plan_generate",
        target_id=request.source_anchor_chapter_id,
        user_visible_title="生成总体构想",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_book_plan,
        task.task_id,
        request,
    )
    return task


@router.post("/book-plan/regenerate")
async def regenerate_book_plan(
    request: BookPlanGenerateRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    return await generate_book_plan(request, background_tasks)


@router.put("/book-plan")
async def update_book_plan(request: BookPlanUpdate) -> BookPlan:
    from app.routers.corpus import _corpus_store

    if request.source_anchor_chapter_id not in _corpus_store:
        raise HTTPException(404, "全书规划的原文锚点章节不存在")
    saved = planning_store.update_book_plan(request)
    planning_store.sync_outline_from_book_plan(saved)
    return writing_project_store.save_book_plan(
        saved.model_copy(update={"accepted": False, "accepted_at": None})
    )


@router.post("/book-plan/accept")
async def accept_book_plan() -> BookPlan:
    book_plan = writing_project_store.load_book_plan() or planning_store.get_book_plan()
    if book_plan is None:
        raise HTTPException(404, "尚未生成总体构想")
    accepted = writing_project_store.accept_book_plan(book_plan)
    planning_store.save_book_plan(accepted)
    planning_store.sync_outline_from_book_plan(accepted)
    if accepted.chapter_plans_complete:
        planning_store.apply_book_plan(accepted, draft_store)
    return accepted


@router.post("/book-plan/complete-chapter-plans")
async def complete_chapter_plans(
    background_tasks: BackgroundTasks,
) -> LongTask:
    book_plan = writing_project_store.load_book_plan() or planning_store.get_book_plan()
    if book_plan is None:
        raise HTTPException(404, "尚未生成总体构想")
    if not book_plan.accepted:
        raise HTTPException(409, "请先审核并接受总体构想，再生成完整章节规划")
    task = task_manager.create(
        TaskType.BOOK_PLAN,
        {
            "operation": "complete_chapter_plans",
            "book_plan_id": book_plan.book_plan_id,
            "target_chapter_count": book_plan.target_chapter_count,
        },
        operation_type="chapter_plans_complete",
        target_id=book_plan.book_plan_id,
        user_visible_title="生成完整章节规划",
        retry_payload={
            "book_plan_id": book_plan.book_plan_id,
        },
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_complete_chapter_plans,
        task.task_id,
        book_plan,
    )
    return task


@router.post("/book-plan/revise")
async def revise_current_book_plan(
    request: BookPlanRevisionRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    book_plan = writing_project_store.load_book_plan() or planning_store.get_book_plan()
    if book_plan is None:
        raise HTTPException(404, "尚未生成总体构想")
    task = task_manager.create(
        TaskType.BOOK_PLAN,
        {
            "operation": "revise",
            "book_plan_id": book_plan.book_plan_id,
            "feedback": request.feedback[:500],
        },
        operation_type="book_plan_revision",
        target_id=book_plan.book_plan_id,
        user_visible_title="修改总体构想",
        retry_payload={"feedback": request.feedback},
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_book_plan_revision,
        task.task_id,
        book_plan,
        request.feedback,
    )
    return task


@router.post("/book-plan/reparse-raw/{temp_id}")
async def reparse_raw_book_plan(temp_id: str) -> BookPlan:
    from app.services.book_planner import normalize_book_plan_payload
    from app.services.model_response_parser import parse_model_json_response

    try:
        record = writing_project_store.get_temp_generation(temp_id)
    except KeyError as exc:
        raise HTTPException(404, "原始构想记录不存在") from exc
    if record.record_type != "book_plan_raw":
        raise HTTPException(400, "该临时记录不是原始构想文本")

    payload, raw_text, parse_error = parse_model_json_response(record.content)
    if payload is None:
        raise HTTPException(
            422,
            parse_error or "原始构想文本仍无法结构化",
        )
    source = record.generation_request
    request = BookPlanGenerateRequest(
        source_anchor_chapter_id=str(
            source.get("source_anchor_chapter_id") or ""
        ),
        rough_direction=str(source.get("rough_direction") or ""),
        target_scale=str(source.get("target_scale") or "medium"),
        target_chapter_count=max(
            3,
            min(60, int(source.get("target_chapter_count") or 18)),
        ),
        automation_level=str(
            source.get("automation_level") or "chapter_by_chapter"
        ),
        auto_create_chapter_plans=False,
    )
    plan = normalize_book_plan_payload(
        payload,
        request,
        prompt_chars=int(source.get("prompt_chars") or 0),
        raw_text=raw_text,
    )
    plan = planning_store.save_book_plan(plan)
    planning_store.sync_outline_from_book_plan(plan)
    plan = writing_project_store.save_book_plan(
        plan.model_copy(update={"accepted": False, "accepted_at": None})
    )
    writing_project_store.save_book_plan_record(plan)
    return plan


@router.post("/book-plan/apply-to-chapter-plans")
async def apply_book_plan_to_chapter_plans() -> list[ChapterPlan]:
    book_plan = planning_store.get_book_plan()
    if book_plan is None:
        raise HTTPException(404, "尚未生成全书规划")
    return planning_store.apply_book_plan(book_plan, draft_store)


async def _run_book_plan(
    task_id: str,
    request: BookPlanGenerateRequest,
) -> None:
    try:
        from app.routers import generation
        from app.routers.corpus import _corpus_store
        from app.services.book_planner import conceive_book_plan

        report = _report_book_plan(task_id)
        task_manager.update(
            task_id,
            status=LongTaskStatus.RUNNING,
            progress=3,
            stage="准备自动构想",
            message="正在读取语料、知识库和已有草稿",
            log="正在读取语料、知识库和已有草稿",
        )
        drafts = [
            draft_store.get_draft(item.draft_id)
            for item in draft_store.list_drafts()
        ]
        book_plan = await conceive_book_plan(
            request=request,
            chapters=list(_corpus_store.values()),
            knowledge_base=generation.get_current_knowledge_base(),
            drafts=drafts,
            progress_callback=report,
        )
        report(88, "保存全书规划", "正在写入 book_plan.json")
        book_plan = planning_store.save_book_plan(book_plan)
        planning_store.sync_outline_from_book_plan(book_plan)
        book_plan = writing_project_store.save_book_plan(
            book_plan.model_copy(update={"accepted": False, "accepted_at": None})
        )
        writing_project_store.save_book_plan_record(book_plan)
        report(94, "等待审核", "总体构想已保存，接受后才会创建章节工程")
        task_manager.succeed(
            task_id,
            {
                "book_plan": book_plan.model_dump(mode="json"),
                "chapter_plans": [],
                "book_plan_file_path": book_plan.file_path,
            },
            "全书自动构想完成，请审核并接受",
        )
    except Exception as exc:
        from app.services.book_planner import BookPlanParseError

        if isinstance(exc, BookPlanParseError) and exc.raw_text.strip():
            record = writing_project_store.save_raw_book_plan(
                raw_text=exc.raw_text,
                request=request.model_dump(mode="json"),
                error_message=str(exc),
                model_name=settings.anthropic_model,
                prompt_chars=exc.prompt_chars,
            )
            task_manager.fail(
                task_id,
                exc,
                result={
                    "raw_book_plan_text": exc.raw_text,
                    "raw_temp_id": record.temp_id,
                    "raw_markdown_path": record.file_path,
                    "raw_json_path": record.generation_request.get(
                        "raw_json_path",
                        "",
                    ),
                    "parse_error": str(exc),
                    "can_reparse": True,
                },
            )
            return
        task_manager.fail(task_id, exc)


async def _run_book_plan_revision(
    task_id: str,
    book_plan: BookPlan,
    feedback: str,
) -> None:
    try:
        from app.services.book_planner import revise_book_plan

        report = _report_book_plan(task_id)
        task_manager.update(
            task_id,
            status=LongTaskStatus.RUNNING,
            progress=10,
            stage="读取总体构想",
            message="正在读取当前总体构想和审核意见",
            log="正在读取当前总体构想和审核意见",
        )
        revised = await revise_book_plan(
            plan=book_plan,
            feedback=feedback,
            progress_callback=report,
        )
        report(88, "保存修改结果", "正在保存修改后的总体构想")
        revised = planning_store.save_book_plan(revised)
        planning_store.sync_outline_from_book_plan(revised)
        revised = writing_project_store.save_book_plan(revised)
        writing_project_store.save_book_plan_record(revised)
        task_manager.succeed(
            task_id,
            {
                "book_plan": revised.model_dump(mode="json"),
                "book_plan_file_path": revised.file_path,
            },
            "总体构想修改完成，请重新审核并接受",
        )
    except Exception as exc:
        from app.services.book_planner import BookPlanParseError

        if isinstance(exc, BookPlanParseError) and exc.raw_text.strip():
            record = writing_project_store.save_raw_book_plan(
                raw_text=exc.raw_text,
                request={
                    "source_anchor_chapter_id": book_plan.source_anchor_chapter_id,
                    "rough_direction": book_plan.rough_direction,
                    "target_scale": book_plan.target_scale,
                    "target_chapter_count": book_plan.target_chapter_count,
                    "automation_level": book_plan.automation_level,
                },
                error_message=str(exc),
                model_name=settings.anthropic_model,
                prompt_chars=exc.prompt_chars,
            )
            task_manager.fail(
                task_id,
                exc,
                result={
                    "raw_book_plan_text": exc.raw_text,
                    "raw_temp_id": record.temp_id,
                    "raw_markdown_path": record.file_path,
                    "raw_json_path": record.generation_request.get(
                        "raw_json_path",
                        "",
                    ),
                    "parse_error": str(exc),
                    "can_reparse": True,
                },
            )
            return
        task_manager.fail(task_id, exc)


async def _run_complete_chapter_plans(
    task_id: str,
    book_plan: BookPlan,
) -> None:
    try:
        from app.services.chapter_planner import (
            book_plan_chapters_complete,
            complete_book_plan_chapters,
        )

        report = _report_book_plan(task_id)
        report(5, "读取总体构想", "正在准备完整章节规划")
        completed, warnings = await complete_book_plan_chapters(
            book_plan,
            progress_callback=report,
        )
        report(90, "保存完整章节规划", "正在保存全书逐章规划")
        completed = planning_store.save_book_plan(completed)
        planning_store.sync_outline_from_book_plan(completed)
        completed = writing_project_store.save_book_plan(completed)
        if not completed.chapter_plans_complete or not book_plan_chapters_complete(completed):
            raise ValueError("18 章详细规划保存后完整性校验未通过")
        plans: list[ChapterPlan] = []
        if completed.accepted:
            plans = planning_store.apply_book_plan(completed, draft_store)
        task_manager.succeed(
            task_id,
            {
                "book_plan": completed.model_dump(mode="json"),
                "chapter_plans": [
                    item.model_dump(mode="json")
                    for item in plans
                    if item.book_plan_id == completed.book_plan_id
                ],
                "warnings": warnings,
                "chapter_plans_complete": completed.chapter_plans_complete,
            },
            f"完整章节规划已生成，共 {len(completed.chapters)} 章",
        )
    except Exception as exc:
        task_manager.fail(task_id, exc)


@router.get("/chapter-plans")
async def list_chapter_plans() -> list[ChapterPlan]:
    return planning_store.list_plans()


@router.post("/chapter-plans")
async def create_chapter_plan(request: ChapterPlanInput) -> ChapterPlan:
    _validate_plan_links(request)
    return planning_store.create_plan(request)


@router.get("/chapter-plans/{plan_id}")
async def get_chapter_plan(plan_id: str) -> ChapterPlan:
    try:
        return planning_store.get_plan(plan_id)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/chapter-plans/{plan_id}")
async def update_chapter_plan(
    plan_id: str,
    request: ChapterPlanInput,
) -> ChapterPlan:
    _validate_plan_links(request)
    try:
        return planning_store.update_plan(plan_id, request)
    except KeyError as exc:
        raise HTTPException(404, "章节规划不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/chapter-plans/{plan_id}")
async def delete_chapter_plan(plan_id: str) -> dict[str, str]:
    try:
        if not planning_store.delete_plan(plan_id):
            raise HTTPException(404, "章节规划不存在")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": plan_id}
