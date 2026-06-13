import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.config import settings
from app.models.schemas import (
    GenerationRequest,
    GenerationResult,
    IterateRequest,
    KnowledgeBase,
)

router = APIRouter()

_generation_results: dict[str, GenerationResult] = {}
_knowledge_base = KnowledgeBase()


def _knowledge_base_ready() -> bool:
    return bool(
        _knowledge_base.characters
        or _knowledge_base.world_settings
        or _knowledge_base.plot_nodes
        or _knowledge_base.themes
    )


@router.get("/knowledge-base")
async def get_knowledge_base() -> KnowledgeBase:
    return _knowledge_base


@router.post("/knowledge-base/build")
async def build_knowledge_base() -> KnowledgeBase:
    global _knowledge_base
    from app.services.knowledge_base import build_kb
    from app.routers.corpus import _corpus_store

    chapters = list(_corpus_store.values())
    if not chapters:
        raise HTTPException(400, "语料库为空，请先扫描本地语料")
    _knowledge_base = await build_kb(chapters)
    if not _knowledge_base_ready():
        raise HTTPException(500, "知识库构建结果为空")
    return _knowledge_base


@router.post("/generate")
async def generate(request: GenerationRequest) -> GenerationResult:
    from app.routers.corpus import _corpus_store
    from app.services.draft_store import draft_store
    from app.services.generator import GenerationServiceError, generate_chapter
    from app.services.planning_store import planning_store

    if request.start_chapter_id not in _corpus_store:
        raise HTTPException(404, "起始章节不存在")
    if not settings.anthropic_api_key:
        raise HTTPException(400, "未配置 API Key")
    if (
        not request.plot_direction.strip()
        and not request.additional_instructions.strip()
        and not request.plan_id
    ):
        raise HTTPException(400, "剧情方向不能为空")
    if not _knowledge_base_ready() and not request.plan_id:
        raise HTTPException(400, "知识库尚未构建，请先构建知识库")

    chapter = _corpus_store[request.start_chapter_id]
    draft_content = ""
    previous_draft_content = ""
    if request.draft_id:
        try:
            draft_content = draft_store.get_draft(request.draft_id).content
        except KeyError as exc:
            raise HTTPException(404, "所选草稿不存在") from exc
    try:
        planning_context = planning_store.compact_context(request.plan_id)
        if request.plan_id:
            planning_store.update_plan_status(request.plan_id, "drafting")
            previous_draft_id = planning_store.previous_draft_id(request.plan_id)
            if previous_draft_id and previous_draft_id != request.draft_id:
                previous_draft_content = draft_store.get_draft(
                    previous_draft_id
                ).content
    except KeyError as exc:
        raise HTTPException(404, "所选章节规划不存在") from exc
    references = [
        _corpus_store[chapter_id]
        for chapter_id in request.reference_chapter_ids
        if chapter_id in _corpus_store
    ][:2]
    ending_state = {"status": "ok", "warning": ""}

    def save_ending(resolution) -> None:
        ending_state["status"] = resolution.status
        ending_state["warning"] = resolution.warning or ""

    try:
        content, system_prompt = await generate_chapter(
            chapter=chapter,
            kb=_knowledge_base,
            request=request,
            draft_content=draft_content,
            previous_draft_content=previous_draft_content,
            planning_context=planning_context,
            reference_chapters=references,
            ending_callback=save_ending,
        )
    except GenerationServiceError as exc:
        raise HTTPException(502, str(exc)) from exc

    result = GenerationResult(
        id=str(uuid.uuid4())[:8],
        request=request,
        content=content,
        system_prompt_used=system_prompt,
        is_partial=ending_state["status"] in {"truncated", "partial"},
        ending_status=ending_state["status"],
        warning=ending_state["warning"],
        can_repair=ending_state["status"] == "partial",
    )
    from app.services.writing_project_store import writing_project_store

    plan = planning_store.get_plan(request.plan_id) if request.plan_id else None
    temp_record = writing_project_store.save_generation_result(
        result,
        record_type=request.generation_kind,
        chapter_order=plan.order if plan else 0,
        chapter_title=plan.title if plan else result.suggested_title,
    )
    result.generation_file_path = temp_record.file_path
    _generation_results[result.id] = result
    draft_store.save_generation(result.id, result.model_dump(mode="json"))
    if request.append_to_draft and request.draft_id:
        appended = draft_store.append_to_draft(request.draft_id, result.content)
        result.accepted = True
        result.saved_draft_id = appended.draft_id
        result.saved_draft_path = appended.file_path
        result.save_status = "auto_saved"
        if request.plan_id:
            planning_store.update_plan_status(request.plan_id, "done")
        draft_store.save_generation(result.id, result.model_dump(mode="json"))
    return result


@router.post("/generate/stream")
async def generate_stream(request: GenerationRequest):
    from app.routers.corpus import _corpus_store
    from app.services.generator import generate_chapter_stream

    if request.start_chapter_id not in _corpus_store:
        raise HTTPException(404, "起始章节不存在")
    if not settings.anthropic_api_key:
        raise HTTPException(400, "未配置 API Key")
    if (
        not request.plot_direction.strip()
        and not request.additional_instructions.strip()
        and not request.plan_id
    ):
        raise HTTPException(400, "剧情方向不能为空")
    if not _knowledge_base_ready() and not request.plan_id:
        raise HTTPException(400, "知识库尚未构建，请先构建知识库")

    chapter = _corpus_store[request.start_chapter_id]

    async def event_stream():
        async for chunk in generate_chapter_stream(
            chapter=chapter,
            kb=_knowledge_base,
            request=request,
        ):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/iterate")
async def iterate(request: IterateRequest) -> GenerationResult:
    from app.services.draft_store import draft_store
    from app.services.generator import GenerationServiceError, iterate_chapter

    if request.generation_id not in _generation_results:
        raise HTTPException(404, "生成结果不存在")
    if not request.feedback.strip():
        raise HTTPException(400, "修改反馈不能为空")
    if not settings.anthropic_api_key:
        raise HTTPException(400, "未配置 API Key")

    prev = _generation_results[request.generation_id]
    original_content = request.current_text.strip() or prev.content
    ending_state = {"status": "ok", "warning": ""}
    revision_state = {
        "revision_mode": request.revision_mode,
        "original_word_count": len("".join(original_content.split())),
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
                "length_ratio": diagnostics.length_ratio,
                "change_level": diagnostics.change_level,
                "requires_confirmation": diagnostics.requires_confirmation,
                "revision_failed": diagnostics.revision_failed,
                "warning": diagnostics.warning,
            }
        )

    try:
        content, system_prompt = await iterate_chapter(
            previous_result=prev,
            feedback=request.feedback,
            target_section=request.target_section,
            kb=_knowledge_base,
            current_text=original_content,
            revision_mode=request.revision_mode,
            ending_callback=save_ending,
            revision_callback=save_revision,
        )
    except GenerationServiceError as exc:
        raise HTTPException(502, str(exc)) from exc

    result = GenerationResult(
        id=str(uuid.uuid4())[:8],
        request=prev.request,
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
    )
    from app.services.planning_store import planning_store
    from app.services.writing_project_store import writing_project_store

    plan = (
        planning_store.get_plan(result.request.plan_id)
        if result.request.plan_id
        else None
    )
    temp_record = writing_project_store.save_generation_result(
        result,
        record_type="revision",
        chapter_order=plan.order if plan else 0,
        chapter_title=plan.title if plan else result.suggested_title,
    )
    result.generation_file_path = temp_record.file_path
    _generation_results[result.id] = result
    draft_store.save_generation(result.id, result.model_dump(mode="json"))
    return result


@router.get("/results/{result_id}")
async def get_result(result_id: str) -> GenerationResult:
    from app.services.draft_store import draft_store

    if result_id not in _generation_results:
        stored = draft_store.load_generation(result_id)
        if stored:
            try:
                _generation_results[result_id] = GenerationResult.model_validate(stored)
            except ValueError:
                pass
    if result_id not in _generation_results:
        raise HTTPException(404, "生成结果不存在")
    return _generation_results[result_id]


@router.get("/results")
async def list_results() -> list[GenerationResult]:
    from app.services.draft_store import draft_store

    combined = dict(_generation_results)
    for payload in draft_store.list_generations():
        try:
            result = GenerationResult.model_validate(payload)
            combined.setdefault(result.id, result)
        except ValueError:
            continue
    return sorted(
        combined.values(),
        key=lambda r: r.created_at,
        reverse=True,
    )


@router.delete("/results/{result_id}")
async def delete_result(result_id: str) -> dict[str, str]:
    from app.services.draft_store import draft_store

    removed_memory = _generation_results.pop(result_id, None) is not None
    try:
        removed_file = draft_store.delete_generation(result_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not removed_memory and not removed_file:
        raise HTTPException(404, "生成结果不存在")
    return {"deleted": result_id}
