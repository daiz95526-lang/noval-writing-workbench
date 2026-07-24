from __future__ import annotations

import math

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.config import settings
from app.models.schemas import (
    AIChapterRepairRequest,
    AIChapterReviewRequest,
    BookPlanGenerateRequest,
    GenerationRequest,
    GenerationResult,
    IterateRequest,
    KnowledgeBuildTaskRequest,
    LongTask,
    LongTaskStatus,
    StyleAnalysisTaskRequest,
    StyleProfile,
    TaskType,
)
from app.services.task_manager import TaskCancelled, task_manager
from app.services.project_context import get_current_project_id, run_in_project

router = APIRouter()


def _task_or_404(task_id: str) -> LongTask:
    task = task_manager.get(task_id, project_id=get_current_project_id())
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


def _progress(task_id: str):
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


@router.get("")
async def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: LongTaskStatus | None = None,
) -> list[LongTask]:
    return task_manager.list(
        limit,
        project_id=get_current_project_id(),
        offset=offset,
        status=status,
    )


@router.get("/{task_id}")
async def get_task(task_id: str) -> LongTask:
    return _task_or_404(task_id)


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str) -> LongTask:
    _task_or_404(task_id)
    return task_manager.cancel(task_id, project_id=get_current_project_id())


@router.post("/{task_id}/retry")
async def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
) -> LongTask:
    original = _task_or_404(task_id)
    try:
        task, payload = task_manager.clone_for_retry(
            task_id,
            get_current_project_id(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    operation = original.operation_type
    runner = None
    args: tuple = ()
    try:
        if operation == TaskType.STYLE_ANALYSIS.value:
            request = StyleAnalysisTaskRequest.model_validate(payload)
            runner, args = _run_style_analysis, (request.chapter_id,)
        elif operation == TaskType.KNOWLEDGE_BUILD.value:
            request = KnowledgeBuildTaskRequest.model_validate(payload)
            runner, args = _run_knowledge_build, (
                request.selected_chapter_id,
                request.summary_only,
            )
        elif operation == TaskType.GENERATION.value:
            request = GenerationRequest.model_validate(payload)
            runner, args = _run_generation, (request,)
        elif operation == TaskType.REVISION.value:
            request = IterateRequest.model_validate(payload)
            runner, args = _run_revision, (request,)
        elif operation == "book_plan_generate":
            from app.routers import planning as planning_router

            request = BookPlanGenerateRequest.model_validate(payload)
            runner, args = planning_router._run_book_plan, (request,)
        elif operation == "chapter_plans_complete":
            from app.routers import planning as planning_router
            from app.services.planning_store import planning_store

            book_plan = planning_store.get_book_plan()
            if book_plan is None:
                raise ValueError("总体构想不存在，无法重试章节规划")
            runner, args = planning_router._run_complete_chapter_plans, (book_plan,)
        elif operation == "book_plan_revision":
            from app.routers import planning as planning_router
            from app.services.planning_store import planning_store

            book_plan = planning_store.get_book_plan()
            if book_plan is None:
                raise ValueError("总体构想不存在，无法重试修改")
            feedback = str(payload.get("feedback") or "").strip()
            if not feedback:
                raise ValueError("历史修改要求为空，无法重试")
            runner, args = planning_router._run_book_plan_revision, (
                book_plan,
                feedback,
            )
        elif operation == TaskType.CHAPTER_REVIEW.value:
            from app.routers import writing as writing_router

            request = AIChapterReviewRequest.model_validate(payload)
            runner, args = writing_router._run_ai_chapter_review, (request,)
        elif operation == TaskType.CHAPTER_REPAIR.value:
            from app.routers import writing as writing_router

            request = AIChapterRepairRequest.model_validate(payload)
            runner, args = writing_router._run_ai_chapter_repair, (request,)
        else:
            raise ValueError("该任务类型暂不支持自动重试")
    except Exception as exc:
        task_manager.fail(task.task_id, exc)
        raise HTTPException(409, str(exc)) from exc

    background_tasks.add_task(
        run_in_project,
        task.project_id,
        runner,
        task.task_id,
        *args,
    )
    return task


@router.post("/style-analysis/start")
async def start_style_analysis(
    request: StyleAnalysisTaskRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.corpus import _corpus_store

    if request.chapter_id not in _corpus_store:
        raise HTTPException(404, "章节不存在")
    chapter = _corpus_store[request.chapter_id]
    task = task_manager.create(
        TaskType.STYLE_ANALYSIS,
        {
            "chapter_id": request.chapter_id,
            "chapter_title": chapter.title,
        },
        target_id=request.chapter_id,
        user_visible_title=f"分析《{chapter.title}》的写作风格",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_style_analysis,
        task.task_id,
        request.chapter_id,
    )
    return task


@router.post("/knowledge-build/start")
async def start_knowledge_build(
    request: KnowledgeBuildTaskRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.corpus import _corpus_store

    if not _corpus_store:
        raise HTTPException(400, "语料库为空，请先扫描本地语料")
    if (
        request.selected_chapter_id
        and request.selected_chapter_id not in _corpus_store
    ):
        raise HTTPException(404, "所选章节不存在")
    task = task_manager.create(
        TaskType.KNOWLEDGE_BUILD,
        {
            "selected_chapter_id": request.selected_chapter_id,
            "summary_only": request.summary_only,
        },
        target_id=request.selected_chapter_id or "corpus",
        user_visible_title="构建项目知识库",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_knowledge_build,
        task.task_id,
        request.selected_chapter_id,
        request.summary_only,
    )
    return task


@router.post("/generation/start")
async def start_generation(
    request: GenerationRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.corpus import _corpus_store
    from app.routers.generation import _knowledge_base_ready
    from app.services.draft_store import draft_store
    from app.services.planning_store import planning_store

    if request.start_chapter_id not in _corpus_store:
        raise HTTPException(404, "起始章节不存在")
    if (
        not request.plot_direction.strip()
        and not request.additional_instructions.strip()
        and not request.plan_id
    ):
        raise HTTPException(400, "剧情方向不能为空")
    if not _knowledge_base_ready() and not request.plan_id:
        raise HTTPException(400, "知识库尚未构建，请先构建知识库")
    if request.draft_id:
        try:
            draft_store.get_draft(request.draft_id)
        except KeyError as exc:
            raise HTTPException(404, "所选草稿不存在") from exc
    if request.plan_id:
        try:
            planning_store.get_plan(request.plan_id)
        except KeyError as exc:
            raise HTTPException(404, "所选章节规划不存在") from exc
    missing_references = [
        chapter_id
        for chapter_id in request.reference_chapter_ids
        if chapter_id not in _corpus_store
    ]
    if missing_references:
        raise HTTPException(404, f"参考章节不存在: {missing_references[0]}")
    total_segments = (
        1
        if request.target_word_count <= 800
        else max(
            2,
            math.ceil(
                request.target_word_count
                / settings.generation_segment_target_words
            ),
        )
    )
    task = task_manager.create(
        TaskType.GENERATION,
        {
            "start_chapter_id": request.start_chapter_id,
            "target_word_count": request.target_word_count,
            "mode": request.mode.value,
            "draft_id": request.draft_id,
            "plan_id": request.plan_id,
            "total_segments": total_segments,
            "pov_character": request.pov_character,
        },
        target_id=request.plan_id or request.start_chapter_id,
        user_visible_title="生成完整章节",
        retry_payload=request.model_dump(mode="json"),
    )
    task.total_segments = total_segments
    task.draft_id = request.draft_id
    task_manager.update(task.task_id)
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_generation,
        task.task_id,
        request,
    )
    return task


@router.post("/revision/start")
async def start_revision(
    request: IterateRequest,
    background_tasks: BackgroundTasks,
) -> LongTask:
    from app.routers.generation import _generation_results

    if request.generation_id not in _generation_results:
        raise HTTPException(404, "生成结果不存在")
    if not request.feedback.strip():
        raise HTTPException(400, "修改反馈不能为空")
    task = task_manager.create(
        TaskType.REVISION,
        {
            "generation_id": request.generation_id,
            "target_section": request.target_section,
            "revision_mode": request.revision_mode,
        },
        target_id=request.generation_id,
        user_visible_title="修改章节候选稿",
        retry_payload=request.model_dump(mode="json"),
    )
    background_tasks.add_task(
        run_in_project,
        task.project_id,
        _run_revision,
        task.task_id,
        request,
    )
    return task


async def _run_style_analysis(task_id: str, chapter_id: str) -> None:
    try:
        from app.routers.analysis import _style_profiles
        from app.routers.corpus import _corpus_store
        from app.services.style_analyzer import analyze_chapter

        report = _progress(task_id)
        report(5, "已接收章节", "风格分析任务已进入后台")
        chapter = _corpus_store.get(chapter_id)
        if chapter is None:
            raise ValueError("章节不存在")
        report(15, "正在读取章节内容", f"已读取《{chapter.title}》")
        diagnostics: dict = {}
        result = await analyze_chapter(
            chapter,
            progress_callback=report,
            diagnostics=diagnostics,
        )
        report(90, "正在解析模型结果", "正在整理分析报告")
        if not result or not any(item.summary.strip() for item in result):
            raise ValueError("分析结果为空")
        profile = StyleProfile(
            id=task_id,
            chapter_ids=[chapter_id],
            dimensions=result,
            global_summary="；".join(
                item.summary for item in result[:3] if item.summary
            ),
            chapter_styles=(
                [diagnostics["chapter_style_json"]]
                if diagnostics.get("chapter_style_json")
                else []
            ),
            warnings=diagnostics.get("warnings", []),
        )
        _style_profiles[profile.id] = profile
        profile_result = {
            "profile_id": profile.id,
            "profile": profile.model_dump(mode="json"),
            "warnings": diagnostics.get("warnings", []),
            "cache_hit": diagnostics.get("cache_hit", False),
        }
        task_manager.succeed(
            task_id,
            profile_result,
            (
                "风格分析完成（模型失败，已使用规则结果）"
                if diagnostics.get("warnings")
                else "风格分析完成"
            ),
        )
    except TaskCancelled:
        return
    except Exception as exc:
        task_manager.fail(task_id, exc)


async def _run_knowledge_build(
    task_id: str,
    selected_chapter_id: str | None,
    summary_only: bool = False,
) -> None:
    try:
        from app.routers import generation
        from app.routers.corpus import _corpus_store
        from app.services.knowledge_base import build_kb

        report = _progress(task_id)
        report(
            3,
            "读取章节",
            "正在读取章节缓存" if summary_only else "正在按卷选择有限样本",
        )
        chapters = list(_corpus_store.values())
        diagnostics: dict = {}
        kb = await build_kb(
            chapters,
            selected_chapter_id=selected_chapter_id,
            summary_only=summary_only,
            progress_callback=report,
            diagnostics=diagnostics,
        )
        report(97, "完成", "正在校验知识库与风格汇总结果")
        if not (
            kb.characters
            or kb.world_settings
            or kb.plot_nodes
            or kb.themes
        ):
            raise ValueError("知识库构建结果为空")
        generation.set_current_knowledge_base(kb)
        kb_result = {
            "knowledge_base": kb.model_dump(mode="json"),
            "summary_failed": diagnostics.get("summary_failed", False),
            "chapter_style_total": diagnostics.get("chapter_style_total", 0),
            "chapter_style_cached": diagnostics.get("chapter_style_cached", 0),
            "chapter_style_analyzed": diagnostics.get("chapter_style_analyzed", 0),
            "chapter_style_skipped": diagnostics.get("chapter_style_skipped", 0),
            "warnings": diagnostics.get("warnings", []),
            "can_retry_summary": diagnostics.get("summary_failed", False),
        }
        if diagnostics.get("summary_failed"):
            task_manager.fail(
                task_id,
                diagnostics.get("last_error")
                or ValueError(
                    "章节级分析已完成，最终汇总失败，可稍后仅重试汇总"
                ),
                result=kb_result,
            )
            return
        task_manager.succeed(
            task_id,
            kb_result,
            (
                f"知识库构建完成，跳过 {diagnostics.get('chapter_style_skipped', 0)} 章"
                if diagnostics.get("chapter_style_skipped")
                else "知识库构建完成"
            ),
        )
    except TaskCancelled:
        return
    except Exception as exc:
        task_manager.fail(task_id, exc)


async def _run_generation(task_id: str, request: GenerationRequest) -> None:
    previous_plan_status = "planned"
    try:
        from app.routers import generation
        from app.routers.corpus import _corpus_store
        from app.services.draft_store import draft_store
        from app.services.generator import generate_chapter
        from app.services.planning_store import planning_store
        from app.services.writing_project_store import writing_project_store

        report = _progress(task_id)
        report(5, "正在校验 API Key", "正在检查模型 API 配置")
        if not settings.anthropic_api_key:
            raise ValueError("未配置 API Key")
        chapter = _corpus_store.get(request.start_chapter_id)
        if chapter is None:
            raise ValueError("起始章节不存在")
        report(15, "正在读取起始章节", f"已读取《{chapter.title}》")
        report(25, "正在读取知识库", "知识库已加载")
        draft_content = ""
        previous_draft_content = ""
        if request.draft_id:
            draft = draft_store.get_draft(request.draft_id)
            draft_content = draft.content
            report(
                28,
                "正在读取当前草稿",
                f"已读取《{draft.title}》，当前 {draft.word_count} 字",
            )
        planning_context = planning_store.compact_context(request.plan_id)
        plan = planning_store.get_plan(request.plan_id) if request.plan_id else None
        if request.plan_id:
            previous_plan_status = plan.status if plan else "planned"
            planning_store.update_plan_status(request.plan_id, "generating")
            report(30, "正在读取章节规划", f"已加载章节规划 {request.plan_id}")
            previous_official = (
                writing_project_store.get_official_chapter_by_order(plan.order - 1)
                if plan and plan.order > 1
                else None
            )
            if previous_official:
                previous_draft_content = previous_official.content[-2000:]
                report(
                    31,
                    "正在读取上一章正式正文",
                    f"已读取第 {previous_official.order} 章结尾用于衔接",
                )
            previous_draft_id = planning_store.previous_draft_id(request.plan_id)
            if (
                not previous_draft_content
                and previous_draft_id
                and previous_draft_id != request.draft_id
            ):
                try:
                    previous_draft_content = draft_store.get_draft(
                        previous_draft_id
                    ).content
                except KeyError:
                    previous_draft_content = ""
        references = [
            _corpus_store[chapter_id]
            for chapter_id in request.reference_chapter_ids
            if chapter_id in _corpus_store
        ][:2]

        def save_partial(
            current_segment: int,
            total_segments: int,
            partial_text: str,
            prompt_chars: int,
        ) -> None:
            task_manager.set_partial_generation(
                task_id,
                current_segment=current_segment,
                total_segments=total_segments,
                partial_text=partial_text,
                draft_id=request.draft_id,
                prompt_chars=prompt_chars,
            )

        ending_state = {
            "status": "ok",
            "warning": "",
        }

        def save_ending(resolution) -> None:
            ending_state["status"] = resolution.status
            ending_state["warning"] = resolution.warning or ""

        content, system_prompt = await generate_chapter(
            chapter=chapter,
            kb=generation.get_current_knowledge_base(),
            request=request,
            progress_callback=report,
            segment_callback=save_partial,
            ending_callback=save_ending,
            draft_content=draft_content,
            previous_draft_content=previous_draft_content,
            planning_context=planning_context,
            reference_chapters=references,
        )
        report(92, "正在检查章节完整性", "正在检查字数、断句、重复和规划覆盖")
        from app.services.chapter_quality import check_chapter_completeness

        completeness = (
            check_chapter_completeness(content, plan)
            if plan
            else None
        )
        report(94, "正在保存生成结果", "正在写入本次生成历史和临时记录")
        result = GenerationResult(
            id=task_id,
            request=request,
            content=content,
            suggested_title=(
                draft.title
                if request.draft_id
                else f"{chapter.title}之后"
            ),
            system_prompt_used=system_prompt,
            is_partial=ending_state["status"] in {"truncated", "partial"},
            ending_status=ending_state["status"],
            warning=ending_state["warning"],
            can_repair=ending_state["status"] == "partial",
            generation_file_path=f"generations/gen_{task_id}.json",
        )
        temp_record = writing_project_store.save_generation_result(
            result,
            record_type=request.generation_kind,
            chapter_order=plan.order if plan else 0,
            chapter_title=plan.title if plan else result.suggested_title,
            completeness_check=(
                completeness.model_dump(mode="json")
                if completeness
                else None
            ),
            chapter_plan_snapshot=(
                plan.model_dump(mode="json")
                if plan
                else None
            ),
        )
        result.generation_file_path = temp_record.file_path
        generation._generation_results[result.id] = result
        if request.plan_id:
            planning_store.update_plan_status(request.plan_id, "draft_review")
        draft_store.save_generation(
            result.id,
            result.model_dump(mode="json"),
        )
        appended_draft = None
        if request.append_to_draft and request.draft_id:
            appended_draft = draft_store.append_to_draft(
                request.draft_id,
                result.content,
            )
            result.accepted = True
            result.saved_draft_id = appended_draft.draft_id
            result.saved_draft_path = appended_draft.file_path
            result.save_status = "auto_saved"
            if request.plan_id:
                planning_store.update_plan_status(request.plan_id, "draft_review")
            draft_store.save_generation(
                result.id,
                result.model_dump(mode="json"),
            )
        total_segments = task_manager.get(task_id).total_segments
        task_manager.set_partial_generation(
            task_id,
            current_segment=total_segments,
            total_segments=total_segments,
            partial_text=content,
            draft_id=request.draft_id,
        )
        result_payload = {
            "generation_result": result.model_dump(mode="json"),
            "temp_generation": temp_record.model_dump(mode="json"),
            "completeness_check": (
                completeness.model_dump(mode="json")
                if completeness
                else None
            ),
            "ending_status": ending_state["status"],
            "warning": ending_state["warning"],
            "partial_text": content,
            "partial_word_count": result.word_count,
            "current_segment": total_segments,
            "total_segments": total_segments,
            "draft_id": request.draft_id,
            "can_accept": (
                completeness.can_save_official
                if completeness
                else True
            ),
            "appended_draft": (
                appended_draft.model_dump(mode="json")
                if appended_draft
                else None
            ),
        }
        if result.is_partial:
            task_manager.partial_succeed(
                task_id,
                result_payload,
                ending_state["warning"]
                or "生成未完全通过末句检查，但正文已保留，可手动编辑或保存。",
            )
        else:
            task_manager.succeed(task_id, result_payload, "续写生成完成")
    except TaskCancelled:
        task = task_manager.get(task_id)
        if task and task.partial_text.strip():
            from app.routers import generation
            from app.services.draft_store import draft_store

            result = GenerationResult(
                id=task_id,
                request=request,
                content=task.partial_text,
                suggested_title="已停止的章节片段",
                is_partial=True,
                generation_file_path=f"generations/gen_{task_id}.json",
            )
            from app.services.writing_project_store import writing_project_store

            temp_record = writing_project_store.save_generation_result(
                result,
                record_type=request.generation_kind,
            )
            result.generation_file_path = temp_record.file_path
            generation._generation_results[result.id] = result
            draft_store.save_generation(
                result.id,
                result.model_dump(mode="json"),
            )
            task_manager.merge_result(
                task_id,
                {
                    "generation_result": result.model_dump(mode="json"),
                    "temp_generation": temp_record.model_dump(mode="json"),
                },
            )
        if request.plan_id:
            planning_store.update_plan_status(
                request.plan_id,
                "draft_review" if task and task.partial_text.strip() else previous_plan_status,
            )
        return
    except Exception as exc:
        partial_text = getattr(exc, "partial_text", "")
        current_segment = int(getattr(exc, "current_segment", 0) or 0)
        total_segments = int(getattr(exc, "total_segments", 0) or 0)
        result_payload: dict = {}
        if partial_text:
            result = GenerationResult(
                id=task_id,
                request=request,
                content=partial_text,
                suggested_title="未完成的章节片段",
                system_prompt_used=getattr(exc, "system_prompt", ""),
                is_partial=True,
                ending_status="partial",
                warning="生成未完全结束，但已保留可用正文。",
                can_repair=True,
                generation_file_path=f"generations/gen_{task_id}.json",
            )
            temp_record = None
            try:
                from app.routers import generation
                from app.services.draft_store import draft_store
                from app.services.writing_project_store import writing_project_store

                temp_record = writing_project_store.save_generation_result(
                    result,
                    record_type=request.generation_kind,
                )
                result.generation_file_path = temp_record.file_path
                generation._generation_results[result.id] = result
                draft_store.save_generation(
                    result.id,
                    result.model_dump(mode="json"),
                )
            except Exception:
                pass
            task_manager.set_partial_generation(
                task_id,
                current_segment=max(0, current_segment - 1),
                total_segments=total_segments,
                partial_text=partial_text,
                draft_id=request.draft_id,
            )
            result_payload = {
                "generation_result": result.model_dump(mode="json"),
                "temp_generation": (
                    temp_record.model_dump(mode="json")
                    if temp_record
                    else None
                ),
                "partial_text": partial_text,
                "partial_word_count": result.word_count,
                "current_segment": max(0, current_segment - 1),
                "total_segments": total_segments,
                "draft_id": request.draft_id,
                "can_accept": True,
                "ending_status": "partial",
                "warning": result.warning,
            }
        if result_payload and result_payload.get("partial_word_count", 0) >= 300:
            if request.plan_id:
                planning_store.update_plan_status(request.plan_id, "draft_review")
            task_manager.partial_succeed(
                task_id,
                result_payload,
                "生成未全部完成，但可用正文已保存为临时记录。",
            )
        else:
            if request.plan_id:
                planning_store.update_plan_status(request.plan_id, previous_plan_status)
            task_manager.fail(task_id, exc, result=result_payload or None)


async def _run_revision(task_id: str, request: IterateRequest) -> None:
    try:
        from app.routers import generation
        from app.services.draft_store import draft_store
        from app.services.generator import iterate_chapter
        from app.services.planning_store import planning_store

        report = _progress(task_id)
        report(10, "正在校验 API Key", "正在检查模型 API 配置")
        if not settings.anthropic_api_key:
            raise ValueError("未配置 API Key")
        previous = generation._generation_results.get(request.generation_id)
        if previous is None:
            raise ValueError("生成结果不存在")
        original_content = request.current_text.strip() or previous.content
        plan = (
            planning_store.get_plan(previous.request.plan_id)
            if previous.request.plan_id
            else None
        )
        ending_state = {
            "status": "ok",
            "warning": "",
        }
        revision_state = {
            "revision_mode": request.revision_mode,
            "original_word_count": len("".join(original_content.split())),
            "revised_word_count": 0,
            "length_ratio": 1.0,
            "change_level": "小幅修改",
            "requires_confirmation": False,
            "revision_failed": False,
            "warning": "",
        }

        def save_ending(resolution) -> None:
            ending_state["status"] = resolution.status
            ending_state["warning"] = resolution.warning or ""

        def save_revision(diagnostics) -> None:
            revision_state.update(
                {
                    "revision_mode": diagnostics.revision_mode,
                    "original_word_count": diagnostics.original_word_count,
                    "revised_word_count": diagnostics.revised_word_count,
                    "length_ratio": diagnostics.length_ratio,
                    "change_level": diagnostics.change_level,
                    "requires_confirmation": diagnostics.requires_confirmation,
                    "revision_failed": diagnostics.revision_failed,
                    "warning": diagnostics.warning,
                }
            )

        from app.models.schemas import TempGenerationCreate
        from app.services.writing_project_store import writing_project_store

        source_record = writing_project_store.create_temp_generation(
            TempGenerationCreate(
                generation_id=f"{task_id}_source",
                chapter_order=plan.order if plan else 0,
                chapter_title=(
                    plan.title
                    if plan
                    else previous.suggested_title or "修改前原文"
                ),
                record_type="revision_source_snapshot",
                content=original_content,
                source_plan_id=previous.request.plan_id,
                generation_request={
                    "source_generation_id": request.generation_id,
                    "revision_mode": request.revision_mode,
                    "feedback": request.feedback,
                    "target_section": request.target_section,
                },
            )
        )
        content, system_prompt = await iterate_chapter(
            previous_result=previous,
            feedback=request.feedback,
            target_section=request.target_section,
            kb=generation.get_current_knowledge_base(),
            current_text=original_content,
            revision_mode=request.revision_mode,
            progress_callback=report,
            ending_callback=save_ending,
            revision_callback=save_revision,
        )
        if not revision_state["revised_word_count"]:
            revision_state["revised_word_count"] = len("".join(content.split()))
            revision_state["length_ratio"] = (
                revision_state["revised_word_count"]
                / max(1, revision_state["original_word_count"])
            )
        report(92, "正在保存生成结果", "正在保存修改后的正文")
        result = GenerationResult(
            id=task_id,
            request=previous.request,
            content=content,
            system_prompt_used=system_prompt,
            is_partial=ending_state["status"] in {"truncated", "partial"},
            ending_status=ending_state["status"],
            warning=revision_state["warning"] or ending_state["warning"],
            can_repair=ending_state["status"] == "partial",
            revision_mode=revision_state["revision_mode"],
            original_word_count=revision_state["original_word_count"],
            revision_change_ratio=revision_state["length_ratio"],
            revision_change_level=revision_state["change_level"],
            revision_requires_confirmation=revision_state["requires_confirmation"],
            revision_failed=revision_state["revision_failed"],
            generation_file_path=f"generations/gen_{task_id}.json",
        )

        from app.services.chapter_quality import check_chapter_completeness

        completeness = (
            check_chapter_completeness(content, plan)
            if plan
            else None
        )
        temp_record = writing_project_store.save_generation_result(
            result,
            record_type="revision",
            chapter_order=plan.order if plan else 0,
            chapter_title=plan.title if plan else result.suggested_title,
            completeness_check=(
                completeness.model_dump(mode="json")
                if completeness
                else None
            ),
            chapter_plan_snapshot=(
                plan.model_dump(mode="json")
                if plan
                else None
            ),
        )
        result.generation_file_path = temp_record.file_path
        generation._generation_results[result.id] = result
        if previous.request.plan_id:
            planning_store.update_plan_status(
                previous.request.plan_id,
                "draft_review",
            )
        draft_store.save_generation(result.id, result.model_dump(mode="json"))
        result_payload = {
            "generation_result": result.model_dump(mode="json"),
            "temp_generation": temp_record.model_dump(mode="json"),
            "completeness_check": (
                completeness.model_dump(mode="json")
                if completeness
                else None
            ),
            "ending_status": ending_state["status"],
            "warning": ending_state["warning"],
            "original_text": original_content,
            "original_word_count": revision_state["original_word_count"],
            "revised_word_count": result.word_count,
            "revision_mode": revision_state["revision_mode"],
            "revision_change_ratio": revision_state["length_ratio"],
            "revision_change_level": revision_state["change_level"],
            "revision_requires_confirmation": revision_state["requires_confirmation"],
            "revision_failed": revision_state["revision_failed"],
            "revision_warning": revision_state["warning"],
            "source_snapshot": source_record.model_dump(mode="json"),
            "can_accept": not revision_state["revision_failed"],
        }
        if (
            result.is_partial
            or revision_state["requires_confirmation"]
            or revision_state["revision_failed"]
        ):
            task_manager.partial_succeed(
                task_id,
                result_payload,
                revision_state["warning"]
                or ending_state["warning"]
                or "修改候选版已生成，请对比原文后决定是否接受。",
            )
        else:
            task_manager.succeed(task_id, result_payload, "修改候选版已生成，请审核后决定是否接受")
    except TaskCancelled:
        return
    except Exception as exc:
        partial_text = getattr(exc, "partial_text", "")
        if partial_text and len("".join(partial_text.split())) >= 300:
            from app.routers import generation
            from app.services.draft_store import draft_store
            from app.services.writing_project_store import writing_project_store

            previous = generation._generation_results.get(request.generation_id)
            if previous is not None:
                result = GenerationResult(
                    id=task_id,
                    request=previous.request,
                    content=partial_text,
                    suggested_title=previous.suggested_title,
                    is_partial=True,
                    ending_status="partial",
                    warning="迭代结果末句可能不完整，已保留可用正文。",
                    can_repair=True,
                )
                temp_record = writing_project_store.save_generation_result(
                    result,
                    record_type="revision",
                )
                result.generation_file_path = temp_record.file_path
                generation._generation_results[result.id] = result
                draft_store.save_generation(
                    result.id,
                    result.model_dump(mode="json"),
                )
                task_manager.set_partial_generation(
                    task_id,
                    current_segment=1,
                    total_segments=1,
                    partial_text=partial_text,
                )
                task_manager.partial_succeed(
                    task_id,
                    {
                        "generation_result": result.model_dump(mode="json"),
                        "temp_generation": temp_record.model_dump(mode="json"),
                        "partial_text": partial_text,
                        "partial_word_count": result.word_count,
                        "can_accept": True,
                        "ending_status": "partial",
                        "warning": result.warning,
                    },
                    result.warning,
                )
                return
        task_manager.fail(task_id, exc)
