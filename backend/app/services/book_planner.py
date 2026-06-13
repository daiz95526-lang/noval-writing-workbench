from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from app.config import settings
from app.models.schemas import (
    BookPlan,
    BookPlanChapter,
    BookPlanGenerateRequest,
    Chapter,
    KnowledgeBase,
)
from app.services.model_response_parser import parse_model_json_response


ProgressCallback = Callable[[float, str, str], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BookPlanParseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        raw_text: str,
        prompt_chars: int,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.prompt_chars = prompt_chars


def _sample_chapter(content: str, limit: int = 1800) -> str:
    text = content.strip()
    if len(text) <= limit:
        return text
    head = int(limit * 0.3)
    middle = int(limit * 0.4)
    tail = limit - head - middle
    center = len(text) // 2
    middle_start = max(head, center - middle // 2)
    return (
        text[:head]
        + "\n...[中段抽样]...\n"
        + text[middle_start:middle_start + middle]
        + "\n...[结尾抽样]...\n"
        + text[-tail:]
    )


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [f"{key}：{item}" for key, item in value.items()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, dict):
        return "；".join(f"{key}：{item}" for key, item in value.items())
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip())
    return str(value).strip()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _raw_text_summary(raw_text: str) -> str:
    compact = " ".join(raw_text.replace("```json", "").replace("```", "").split())
    return compact[:800]


class BookPlanner:
    def __init__(self) -> None:
        self._client = (
            Anthropic(
                api_key=settings.anthropic_api_key,
                base_url=settings.anthropic_base_url or None,
                max_retries=0,
            )
            if settings.anthropic_api_key
            else None
        )

    async def generate(
        self,
        *,
        request: BookPlanGenerateRequest,
        chapters: list[Chapter],
        knowledge_base: KnowledgeBase,
        drafts: list,
        progress_callback: ProgressCallback | None = None,
    ) -> BookPlan:
        if not self._client:
            raise ValueError("未配置 API Key，无法自动构想全书规划")
        anchor = next(
            (
                chapter
                for chapter in chapters
                if chapter.chapter_id == request.source_anchor_chapter_id
            ),
            None,
        )
        if anchor is None:
            raise ValueError("自动构想的原文锚点章节不存在")
        if progress_callback:
            progress_callback(12, "读取章节", f"已读取原文锚点《{anchor.title}》")
        prompt = self._build_prompt(
            request=request,
            chapters=chapters,
            anchor=anchor,
            knowledge_base=knowledge_base,
            drafts=drafts,
        )
        truncated = len(prompt) > settings.book_plan_prompt_max_chars
        prompt = prompt[: settings.book_plan_prompt_max_chars]
        if progress_callback:
            progress_callback(
                38,
                "整理构想上下文",
                f"Book Plan Prompt 字符数：{len(prompt)}"
                + ("，已自动截断" if truncated else ""),
            )
            progress_callback(
                52,
                "模型自动构想",
                f"正在生成 {request.target_chapter_count} 章全书规划，仅调用一次模型",
            )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=settings.anthropic_model,
                    max_tokens=settings.book_plan_max_tokens,
                    system=(
                        "你是长篇小说总编剧。只输出一个有效 JSON 对象；"
                        "不要 Markdown、代码块、解释、前缀或思考过程；"
                        "字段名和字符串全部使用英文双引号。"
                    ),
                    messages=[{"role": "user", "content": prompt}],
                    timeout=settings.book_plan_timeout_seconds,
                ),
                timeout=settings.book_plan_timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"全书自动构想模型请求失败 ({type(exc).__name__}): {exc}"
            ) from exc
        payload, raw_text, parse_error = parse_model_json_response(response)
        if payload is None:
            raise BookPlanParseError(
                parse_error or "全书自动构想返回的 JSON 无法解析",
                raw_text=raw_text,
                prompt_chars=len(prompt),
            )
        if progress_callback:
            progress_callback(82, "解析规划", "正在校验全书主线与逐章规划")
        return self._normalize_plan(payload, request, len(prompt), raw_text)

    async def revise(
        self,
        *,
        plan: BookPlan,
        feedback: str,
        progress_callback: ProgressCallback | None = None,
    ) -> BookPlan:
        if not self._client:
            raise ValueError("未配置 API Key，无法修改总体构想")
        source = json.dumps(
            plan.model_dump(
                mode="json",
                exclude={
                    "accepted",
                    "accepted_at",
                    "file_path",
                    "created_at",
                    "updated_at",
                },
            ),
            ensure_ascii=False,
        )
        prompt = (
            "请根据修改要求调整这份全书总体构想。保留未被要求改变的内容，"
            "仍然只输出与输入相同结构的完整 JSON。\n\n"
            f"修改要求：{feedback}\n\n当前总体构想：\n{source}"
        )
        prompt = prompt[: settings.book_plan_prompt_max_chars]
        if progress_callback:
            progress_callback(
                40,
                "修改总体构想",
                f"正在按审核意见修改，Prompt 字符数：{len(prompt)}",
            )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=settings.anthropic_model,
                    max_tokens=settings.book_plan_max_tokens,
                    system=(
                        "你是长篇小说总编剧。只输出一个有效 JSON 对象；"
                        "不要 Markdown、代码块、解释、前缀或思考过程；"
                        "字段名和字符串全部使用英文双引号。"
                    ),
                    messages=[{"role": "user", "content": prompt}],
                    timeout=settings.book_plan_timeout_seconds,
                ),
                timeout=settings.book_plan_timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(
                f"总体构想修改请求失败 ({type(exc).__name__}): {exc}"
            ) from exc
        payload, raw_text, parse_error = parse_model_json_response(response)
        if payload is None:
            raise BookPlanParseError(
                parse_error or "修改后的总体构想 JSON 无法解析",
                raw_text=raw_text,
                prompt_chars=len(prompt),
            )
        request = BookPlanGenerateRequest(
            source_anchor_chapter_id=plan.source_anchor_chapter_id,
            rough_direction=plan.rough_direction,
            target_scale=plan.target_scale,
            target_chapter_count=plan.target_chapter_count,
            automation_level=plan.automation_level,
            auto_create_chapter_plans=False,
        )
        revised = self._normalize_plan(payload, request, len(prompt), raw_text)
        return revised.model_copy(
            update={
                "book_plan_id": plan.book_plan_id,
                "created_at": plan.created_at,
                "accepted": False,
                "accepted_at": None,
            }
        )

    def _build_prompt(
        self,
        *,
        request: BookPlanGenerateRequest,
        chapters: list[Chapter],
        anchor: Chapter,
        knowledge_base: KnowledgeBase,
        drafts: list,
    ) -> str:
        ordered = sorted(
            chapters,
            key=lambda item: (item.series_order, item.chapter_order),
        )
        anchor_index = ordered.index(anchor)
        source_samples = ordered[max(0, anchor_index - 2):anchor_index + 1]
        source_context = "\n\n".join(
            f"### {item.volume_display_name} / {item.title}\n{_sample_chapter(item.content)}"
            for item in source_samples
        )
        character_context = "\n".join(
            f"- {item.name}：{item.personality[:180]}；说话方式：{item.speech_style[:100]}"
            for item in knowledge_base.characters[:8]
        )
        setting_context = "\n".join(
            f"- {item.name}：{item.description[:180]}"
            for item in knowledge_base.world_settings[:6]
        )
        plot_context = "\n".join(
            f"- {item.title}：{item.summary[:180]}"
            for item in knowledge_base.plot_nodes[-8:]
        )
        style = knowledge_base.style_knowledge
        style_rules = []
        if style:
            style_rules.extend(style.global_character_rules[:2])
            style_rules.extend(style.global_dialogue_rules[:2])
            style_rules.extend(style.global_worldbuilding_rules[:2])
            style_rules.extend(style.plot_continuity_rules[:2])
        style_context = "\n".join(f"- {item}" for item in style_rules[:8])
        draft_context = "\n\n".join(
            f"### 已有草稿《{item.title}》\n{item.content[-700:]}"
            for item in sorted(drafts, key=lambda value: value.updated_at)[-3:]
            if item.content.strip()
        )
        volume_groups: dict[str, list[Chapter]] = {}
        for item in ordered:
            volume_groups.setdefault(item.volume_display_name, []).append(item)
        volume_context = "\n".join(
            (
                f"- {name}：共 {len(items)} 章，"
                f"从《{items[0].title}》到《{items[-1].title}》，"
                f"约 {sum(item.word_count for item in items)} 字"
            )
            for name, items in volume_groups.items()
        )
        direction = request.rough_direction.strip() or "未提供，由模型根据原作锚点自主构想。"
        return f"""
请基于以下有限上下文，为小说续写生成可执行的全书级 Book Plan。

硬性要求：
1. 一共输出 {request.target_chapter_count} 章，章节 order 从 1 连续编号。
2. 不改写原作已有事实，不复述原作整章，不模仿或复制原文长句。
3. 首次构想只生成全书骨架和章节目录，避免输出过长导致 JSON 截断。
4. 粗略方向允许为空；为空时请自主选择最符合已有矛盾的发展。
5. 先比较龙族 I-V 各卷侧重点、人物状态、未解冲突和伏笔；relation_to_previous_books
   必须说明为什么下一部自然承接这个故事、为什么选择这些重点人物。
6. 每章只输出标题和一句话简介；详细情节节点由后续章节生成阶段补充。
7. 只返回 JSON，不要 Markdown，不要解释文字，不要代码块，不要任何前缀。
8. 所有字段名和字符串必须使用英文双引号。
9. chapters 必须是数组，chapter_count 必须等于 chapters 数量。
10. 必须符合以下精简 schema：
{{
  "title": "",
  "premise": "",
  "core_theme": "",
  "focus_characters": [],
  "main_conflict": "",
  "hidden_conflict": "",
  "central_mystery": "",
  "relation_to_previous_books": "",
  "tone": "",
  "ending_direction": "",
  "chapter_count": {request.target_chapter_count},
  "chapters": [
    {{
      "order": 1,
      "title": "",
      "summary": ""
    }}
  ]
}}

规划规模：{request.target_scale}
自动化等级：{request.automation_level}
用户粗略方向：{direction}

## 龙族 I-V 卷册概览
{volume_context or "- 暂无卷册统计"}

## 原文锚点与相邻章节抽样
{source_context}

## 关键角色
{character_context or "- 暂无结构化角色资料，请仅依据锚点文本判断"}

## 关键设定
{setting_context or "- 暂无结构化设定资料"}

## 最近情节节点
{plot_context or "- 暂无结构化情节节点"}

## 风格与连续性规则（最多 8 条）
{style_context or "- 保持第三人称贴近人物、对话自然、避免信息堆砌"}

## 已有续写草稿尾部
{draft_context or "- 暂无已有续写草稿"}
""".strip()

    def _normalize_plan(
        self,
        payload: dict,
        request: BookPlanGenerateRequest,
        prompt_chars: int,
        raw_text: str = "",
    ) -> BookPlan:
        raw_chapters = payload.get("chapters")
        if isinstance(raw_chapters, dict):
            raw_chapters = list(raw_chapters.values())
        elif not isinstance(raw_chapters, list):
            raw_chapters = []
        default_words = {
            "short": 1600,
            "medium": 2200,
            "long": 2800,
        }[request.target_scale]
        chapters: list[BookPlanChapter] = []
        chapter_limit = min(60, max(0, _safe_int(
            payload.get("chapter_count"),
            len(raw_chapters),
        )))
        if chapter_limit <= 0 and raw_chapters:
            chapter_limit = len(raw_chapters)
        for index, raw in enumerate(raw_chapters[:chapter_limit or len(raw_chapters)], 1):
            value = raw if isinstance(raw, dict) else {}
            summary = _safe_text(
                value.get("summary")
                or value.get("chapter_summary")
                or value.get("chapter_goal")
                or value.get("description")
            )
            chapters.append(
                BookPlanChapter(
                    order=index,
                    title=_safe_text(value.get("title"), f"第{index}章"),
                    chapter_summary=summary,
                    chapter_goal=summary,
                    plot_beats=_string_list(value.get("plot_beats")),
                    chapter_function=(
                        _string_list(value.get("chapter_function"))
                        or ([summary] if summary else [])
                    ),
                    characters=_string_list(value.get("characters")),
                    conflict=_safe_text(value.get("conflict")),
                    foreshadowing_to_plant=_string_list(
                        value.get("foreshadowing_to_plant")
                    ),
                    foreshadowing_to_resolve=_string_list(
                        value.get("foreshadowing_to_resolve")
                    ),
                    ending_hook=_safe_text(value.get("ending_hook")),
                    target_words=max(
                        300,
                        min(5000, _safe_int(value.get("target_words"), default_words)),
                    ),
                )
            )
        if raw_chapters and chapter_limit > len(chapters):
            for order in range(len(chapters) + 1, chapter_limit + 1):
                chapters.append(
                    BookPlanChapter(
                        order=order,
                        title=f"第{order}章（待补全）",
                        chapter_summary="模型原始输出在此处截断，需要生成完整章节规划。",
                        chapter_goal="模型原始输出在此处截断，可通过修改总体构想补全。",
                        chapter_function=["补全全书章节目录"],
                        target_words=default_words,
                    )
                )
        now = _now()
        return BookPlan(
            source_anchor_chapter_id=request.source_anchor_chapter_id,
            rough_direction=request.rough_direction,
            target_scale=request.target_scale,
            target_chapter_count=max(
                1,
                len(chapters)
                or _safe_int(
                    payload.get("chapter_count"),
                    request.target_chapter_count,
                ),
            ),
            automation_level=request.automation_level,
            title=_safe_text(payload.get("title"), "龙族 VI：未命名续写"),
            premise=_safe_text(payload.get("premise")) or _raw_text_summary(raw_text),
            core_theme=_safe_text(payload.get("core_theme") or payload.get("theme")),
            focus_characters=_string_list(payload.get("focus_characters")),
            main_conflict=_safe_text(
                payload.get("main_conflict") or payload.get("major_plotlines")
            ),
            hidden_conflict=_safe_text(payload.get("hidden_conflict")),
            central_mystery=_safe_text(payload.get("central_mystery")),
            relation_to_previous_books=_safe_text(
                payload.get("relation_to_previous_books") or ""
            ),
            old_foreshadowing_to_resolve=_string_list(
                payload.get("old_foreshadowing_to_resolve")
            ),
            new_foreshadowing_to_plant=_string_list(
                payload.get("new_foreshadowing_to_plant")
            ),
            main_locations=_string_list(payload.get("main_locations")),
            tone=_safe_text(payload.get("tone")),
            opening_setup=_safe_text(payload.get("opening_setup")),
            midpoint_turn=_safe_text(payload.get("midpoint_turn")),
            ending_direction=_safe_text(payload.get("ending_direction")),
            continuity_notes=(
                _string_list(payload.get("continuity_notes"))
                or _string_list(payload.get("major_plotlines"))
            ),
            character_arcs=_string_list(payload.get("character_arcs")),
            foreshadowing=_string_list(
                payload.get("foreshadowing")
                or payload.get("foreshadowing_plan")
            ),
            prohibitions=_string_list(payload.get("prohibitions")),
            chapters=chapters,
            model_name=settings.anthropic_model,
            prompt_chars=prompt_chars,
            generation_source="model",
            chapter_plans_complete=False,
            chapter_plans_completed_at=None,
            created_at=now,
            updated_at=now,
        )


async def conceive_book_plan(**kwargs) -> BookPlan:
    return await BookPlanner().generate(**kwargs)


async def revise_book_plan(**kwargs) -> BookPlan:
    return await BookPlanner().revise(**kwargs)


def normalize_book_plan_payload(
    payload: dict,
    request: BookPlanGenerateRequest,
    *,
    prompt_chars: int = 0,
    raw_text: str = "",
) -> BookPlan:
    return BookPlanner()._normalize_plan(
        payload,
        request,
        prompt_chars,
        raw_text,
    )
