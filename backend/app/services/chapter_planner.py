from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone

from anthropic import Anthropic

from app.config import settings
from app.models.schemas import BookPlan, BookPlanChapter
from app.services.model_response_parser import parse_model_json_response


ProgressCallback = Callable[[float, str, str], None]
_BATCH_SIZE = 3
_PLACEHOLDER_PATTERN = re.compile(
    r"待定|待补|未规划|后续展开|暂无|tbd|placeholder|"
    r"模型原始输出.*截断|补全全书章节目录",
    flags=re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def chapter_plan_is_complete(chapter: BookPlanChapter) -> bool:
    required_text = (
        (chapter.title, 2),
        (chapter.chapter_summary, 16),
        (chapter.chapter_goal, 12),
        (chapter.opening_state, 12),
        (chapter.ending_state, 12),
        (chapter.previous_bridge, 10),
        (chapter.next_bridge, 10),
        (chapter.conflict, 12),
        (chapter.emotional_tone, 4),
        (chapter.word_count_reason, 12),
    )
    if any(
        len(value.strip()) < minimum or _PLACEHOLDER_PATTERN.search(value)
        for value, minimum in required_text
    ):
        return False
    return (
        bool(_clean_values(chapter.chapter_function))
        and len(chapter.plot_beats) >= 3
        and bool(_clean_values(chapter.characters))
        and 1200 <= chapter.target_words <= 8000
    )


def book_plan_chapters_complete(plan: BookPlan) -> bool:
    if len(plan.chapters) != plan.target_chapter_count or not plan.chapters:
        return False
    orders = [chapter.order for chapter in plan.chapters]
    return (
        orders == list(range(1, len(plan.chapters) + 1))
        and all(chapter_plan_is_complete(chapter) for chapter in plan.chapters)
    )


class ChapterPlanCompleter:
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

    async def complete(
        self,
        plan: BookPlan,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[BookPlan, list[str]]:
        if not self._client:
            raise ValueError("未配置 API Key，无法生成完整章节规划")
        skeletons = self._ensure_skeletons(plan)
        completed_by_order = {
            item.order: item
            for item in skeletons
            if chapter_plan_is_complete(item)
        }
        pending = [
            item for item in skeletons
            if item.order not in completed_by_order
        ]
        warnings: list[str] = []
        total_batches = max(1, (len(pending) + _BATCH_SIZE - 1) // _BATCH_SIZE)

        for batch_index, start in enumerate(range(0, len(pending), _BATCH_SIZE), 1):
            batch = pending[start:start + _BATCH_SIZE]
            if progress_callback:
                progress_callback(
                    10 + (batch_index - 1) / total_batches * 75,
                    f"正在规划第 {batch[0].order}-{batch[-1].order} 章",
                    f"正在生成第 {batch_index}/{total_batches} 批详细章节规划",
                )
            try:
                detailed = await self._complete_batch(plan, skeletons, batch)
            except Exception as exc:
                detailed = []
                warnings.append(
                    f"第 {batch[0].order}-{batch[-1].order} 章模型细化失败，"
                    f"已使用结构化兜底：{type(exc).__name__}"
                )
            by_order = {item.order: item for item in detailed}
            for skeleton in batch:
                candidate = by_order.get(skeleton.order)
                if candidate is None or not chapter_plan_is_complete(candidate):
                    candidate = self._fallback_detail(plan, skeleton, skeletons)
                completed_by_order[skeleton.order] = candidate

        completed = [
            completed_by_order.get(item.order)
            or self._fallback_detail(plan, item, skeletons)
            for item in skeletons
        ]
        completed = [
            item
            if chapter_plan_is_complete(item)
            else self._fallback_detail(plan, item, completed)
            for item in completed
        ]
        completed.sort(key=lambda item: item.order)
        is_complete = all(chapter_plan_is_complete(item) for item in completed)
        if not is_complete:
            missing = [
                str(item.order)
                for item in completed
                if not chapter_plan_is_complete(item)
            ]
            raise ValueError(f"章节规划最终校验未通过：第 {', '.join(missing)} 章")
        result = plan.model_copy(
            update={
                "chapters": completed,
                "target_chapter_count": len(completed),
                "chapter_plans_complete": True,
                "chapter_plans_completed_at": _now(),
                "updated_at": _now(),
            }
        )
        return result, warnings

    async def _complete_batch(
        self,
        plan: BookPlan,
        skeletons: list[BookPlanChapter],
        batch: list[BookPlanChapter],
    ) -> list[BookPlanChapter]:
        first_order = batch[0].order
        previous = next(
            (item for item in skeletons if item.order == first_order - 1),
            None,
        )
        following = next(
            (item for item in skeletons if item.order == batch[-1].order + 1),
            None,
        )
        compact_plan = {
            "title": plan.title,
            "premise": plan.premise,
            "core_theme": plan.core_theme,
            "focus_characters": plan.focus_characters,
            "main_conflict": plan.main_conflict,
            "hidden_conflict": plan.hidden_conflict,
            "central_mystery": plan.central_mystery,
            "tone": plan.tone,
            "opening_setup": plan.opening_setup,
            "midpoint_turn": plan.midpoint_turn,
            "ending_direction": plan.ending_direction,
        }
        batch_skeleton = [
            {
                "order": item.order,
                "title": item.title,
                "summary": item.chapter_summary or item.chapter_goal,
            }
            for item in batch
        ]
        prompt = f"""
请细化长篇小说的第 {batch[0].order}-{batch[-1].order} 章规划。
只输出 JSON，不要 Markdown、解释或前缀。chapters 必须正好包含本批章节。

总体构想：
{json.dumps(compact_plan, ensure_ascii=False)}

本批章节骨架：
{json.dumps(batch_skeleton, ensure_ascii=False)}

前一章骨架：
{json.dumps(_brief(previous), ensure_ascii=False)}

后一章骨架：
{json.dumps(_brief(following), ensure_ascii=False)}

每章必须输出：
order, title, chapter_summary, chapter_goal, chapter_function,
opening_state, ending_state, previous_bridge, next_bridge, conflict,
plot_beats（至少4条）, characters, foreshadowing_to_plant,
foreshadowing_to_resolve, emotional_tone, suggested_word_count,
word_count_reason, ending_hook。

字数规则：
- 普通章 2500-6000 字；
- 过渡章最低 1200 字；
- 关键高潮章默认不超过 8000 字；
- 必须说明 word_count_reason。
禁止使用“待定、待补充、未规划、后续展开、暂无、TBD、placeholder”。
""".strip()
        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._client.messages.create,
                model=settings.anthropic_model,
                max_tokens=min(settings.book_plan_max_tokens, 2400),
                system="你是长篇小说章节规划师。只输出严格 JSON 对象。",
                messages=[{"role": "user", "content": prompt}],
                timeout=settings.book_plan_timeout_seconds,
            ),
            timeout=settings.book_plan_timeout_seconds,
        )
        payload, _raw_text, error = parse_model_json_response(response)
        if payload is None:
            raise ValueError(error or "详细章节规划 JSON 无法解析")
        values = payload.get("chapters")
        if not isinstance(values, list):
            return []
        return [
            _normalize_detail(item, fallback)
            for item, fallback in zip(values, batch)
            if isinstance(item, dict)
        ]

    @staticmethod
    def _ensure_skeletons(plan: BookPlan) -> list[BookPlanChapter]:
        chapters = sorted(plan.chapters, key=lambda item: item.order)
        by_order = {item.order: item for item in chapters}
        count = max(plan.target_chapter_count, len(chapters), 1)
        values: list[BookPlanChapter] = []
        for order in range(1, count + 1):
            current = by_order.get(order)
            if current is None:
                current = BookPlanChapter(
                    order=order,
                    title=_fallback_title(order, count),
                    chapter_summary=f"推进《{plan.title}》的核心冲突至第 {order} 阶段。",
                    chapter_goal=f"推动主线进入第 {order} 个关键节点。",
                    target_words=_suggested_words(order, count),
                )
            fallback_title = _fallback_title(order, count)
            current = current.model_copy(
                update={
                    "title": _clean_text(current.title, fallback_title),
                    "chapter_summary": _clean_text(
                        current.chapter_summary,
                        "",
                    ),
                    "chapter_goal": _clean_text(current.chapter_goal, ""),
                    "chapter_function": _clean_values(current.chapter_function),
                    "characters": _clean_values(current.characters),
                }
            )
            values.append(current)
        return values

    @staticmethod
    def _fallback_detail(
        plan: BookPlan,
        skeleton: BookPlanChapter,
        all_skeletons: list[BookPlanChapter],
    ) -> BookPlanChapter:
        count = len(all_skeletons)
        previous = next(
            (item for item in all_skeletons if item.order == skeleton.order - 1),
            None,
        )
        following = next(
            (item for item in all_skeletons if item.order == skeleton.order + 1),
            None,
        )
        target_words = _suggested_words(skeleton.order, count)
        title = _clean_text(skeleton.title, _fallback_title(skeleton.order, count))
        phase_summary = _phase_summary(plan, skeleton.order, count, title)
        summary = _clean_text(
            skeleton.chapter_summary or skeleton.chapter_goal,
            phase_summary,
        )
        if len(summary) < 16:
            summary = phase_summary
        chapter_goal = _clean_text(
            skeleton.chapter_goal,
            f"完成《{title}》中的关键行动与人物选择，并推动主线产生不可逆变化。",
        )
        if len(chapter_goal) < 12:
            chapter_goal = (
                f"推动《{title}》的核心冲突升级，让人物选择改变后续局势。"
            )
        return BookPlanChapter(
            order=skeleton.order,
            title=title,
            chapter_summary=summary,
            chapter_goal=chapter_goal,
            opening_state=_clean_text(
                skeleton.opening_state,
                (
                    f"承接上一章《{previous.title}》造成的局势与人物选择。"
                    if previous
                    else plan.opening_setup or "承接原著结尾，核心人物重新进入危机。"
                ),
            ),
            ending_state=_clean_text(
                skeleton.ending_state,
                (
                    f"本章冲突形成阶段性结果，并让主线进入第 {skeleton.order + 1} 阶段。"
                    if following
                    else f"核心冲突完成收束，并落到全书结尾方向：{plan.ending_direction}"
                ),
            ),
            previous_bridge=_clean_text(
                skeleton.previous_bridge,
                (
                    f"从《{previous.title}》的结尾事件直接切入本章行动。"
                    if previous
                    else "从原著锚点和全书开局局面自然切入。"
                ),
            ),
            next_bridge=_clean_text(
                skeleton.next_bridge,
                (
                    f"以新线索或未完成行动引向下一章《{following.title}》。"
                    if following
                    else f"收束至全书结尾方向：{plan.ending_direction or '完成阶段性选择'}。"
                ),
            ),
            plot_beats=_clean_values(skeleton.plot_beats) or [
                "承接上一章结果并确认当前目标",
                "角色采取行动，核心冲突升级",
                "出现信息或立场转折",
                "形成阶段结果并留下下一章入口",
            ],
            chapter_function=_clean_values(skeleton.chapter_function) or [
                "推进主线",
                "发展人物关系",
                "建立前后章衔接",
            ],
            characters=_clean_values(skeleton.characters)
            or plan.focus_characters[:4]
            or ["核心人物"],
            conflict=_clean_text(
                skeleton.conflict,
                plan.main_conflict or "角色目标与现实代价发生正面冲突。",
            ),
            foreshadowing_to_plant=skeleton.foreshadowing_to_plant,
            foreshadowing_to_resolve=skeleton.foreshadowing_to_resolve,
            emotional_tone=_clean_text(
                skeleton.emotional_tone,
                plan.tone or "紧张中保留克制的人物情绪",
            ),
            word_count_reason=_clean_text(
                skeleton.word_count_reason,
                _word_count_reason(skeleton.order, count, target_words),
            ),
            ending_hook=_clean_text(
                skeleton.ending_hook,
                (
                    f"章末出现直接通往《{following.title}》的新变化。"
                    if following
                    else "以完成选择后的余波收束全书。"
                ),
            ),
            target_words=target_words,
        )


def _brief(chapter: BookPlanChapter | None) -> dict:
    if chapter is None:
        return {}
    return {
        "order": chapter.order,
        "title": chapter.title,
        "summary": chapter.chapter_summary or chapter.chapter_goal,
    }


def _normalize_detail(value: dict, fallback: BookPlanChapter) -> BookPlanChapter:
    def text(key: str, default: str = "") -> str:
        result = value.get(key)
        return str(result).strip() if result is not None else default

    def values(key: str) -> list[str]:
        result = value.get(key)
        if isinstance(result, list):
            return [str(item).strip() for item in result if str(item).strip()]
        if isinstance(result, dict):
            return [f"{key_name}：{item}" for key_name, item in result.items()]
        if isinstance(result, str) and result.strip():
            return [result.strip()]
        return []

    raw_words = value.get("suggested_word_count", value.get("target_words"))
    try:
        target_words = int(raw_words)
    except (TypeError, ValueError):
        target_words = fallback.target_words
    target_words = max(1200, min(8000, target_words))
    summary = text(
        "chapter_summary",
        text("summary", fallback.chapter_summary or fallback.chapter_goal),
    )
    return BookPlanChapter(
        order=fallback.order,
        title=text("title", fallback.title),
        chapter_summary=summary,
        chapter_goal=text("chapter_goal", summary),
        opening_state=text("opening_state"),
        ending_state=text("ending_state"),
        previous_bridge=text("previous_bridge"),
        next_bridge=text("next_bridge"),
        plot_beats=values("plot_beats"),
        chapter_function=values("chapter_function"),
        characters=values("characters"),
        conflict=text("main_conflict", text("conflict")),
        foreshadowing_to_plant=values("foreshadowing_to_plant"),
        foreshadowing_to_resolve=values("foreshadowing_to_resolve"),
        emotional_tone=text("emotional_tone"),
        word_count_reason=text("word_count_reason"),
        ending_hook=text("ending_hook"),
        target_words=target_words,
    )


def _clean_values(values: list[str]) -> list[str]:
    return [
        text
        for item in values
        if (text := str(item).strip())
        and not _PLACEHOLDER_PATTERN.search(text)
    ]


def _phase_summary(
    plan: BookPlan,
    order: int,
    count: int,
    title: str,
) -> str:
    protagonist = plan.focus_characters[0] if plan.focus_characters else "核心人物"
    conflict = plan.main_conflict or "全书核心危机"
    ratio = order / max(count, 1)
    if order == 1:
        action = "从原著锚点接续异常征兆，确认新的危机已经开始"
    elif ratio <= 0.33:
        action = "集结关键同伴并追查线索，让外部威胁与人物分歧同时升级"
    elif ratio <= 0.55:
        action = "深入危机中心取得关键证据，并揭开足以改变行动方向的真相"
    elif ratio <= 0.75:
        action = "围绕新真相重组计划，让多条人物线在正面冲突中汇合"
    elif order < count:
        action = "进入最终行动并支付前期选择的代价，为终局抉择清除最后障碍"
    else:
        action = "完成终局抉择、核心冲突收束与主要人物余波"
    return (
        f"《{title}》中，{protagonist}{action}；本章围绕“{conflict}”"
        "形成明确的阶段结果，并把因果链交给下一章。"
    )


def _clean_text(value: str, fallback: str) -> str:
    text = value.strip()
    if not text or _PLACEHOLDER_PATTERN.search(text):
        return fallback
    return text


def _fallback_title(order: int, count: int) -> str:
    phases = [
        "暗潮初现",
        "失落的信号",
        "旧日回声",
        "雪原来客",
        "裂隙之门",
        "错误的答案",
        "深海灯火",
        "王座阴影",
        "逆行者",
        "无人归途",
        "沉默契约",
        "世界树下",
        "最后的筹码",
        "黑王之梦",
        "献祭之夜",
        "零点钟声",
        "重生之前",
        "余烬与黎明",
    ]
    return phases[(order - 1) % len(phases)] + (f"·{order}" if count > len(phases) else "")


def _suggested_words(order: int, count: int) -> int:
    if order == 1:
        return 3200
    if order == count:
        return 4600
    if order >= max(2, count - 2):
        return 5200
    if order in {max(2, count // 2), max(3, count // 2 + 1)}:
        return 4600
    return 3600


def _word_count_reason(order: int, count: int, words: int) -> str:
    if order == 1:
        role = "开篇需要完成承接原著、人物入场和危机建立"
    elif order == count:
        role = "终章需要完成冲突收束、人物选择和余波"
    elif order >= count - 2:
        role = "高潮段需要容纳多线汇合与关键行动"
    else:
        role = "普通推进章需要兼顾行动、人物反应和章末转折"
    return f"{role}，建议约 {words} 字。"


async def complete_book_plan_chapters(
    plan: BookPlan,
    progress_callback: ProgressCallback | None = None,
) -> tuple[BookPlan, list[str]]:
    return await ChapterPlanCompleter().complete(plan, progress_callback)
