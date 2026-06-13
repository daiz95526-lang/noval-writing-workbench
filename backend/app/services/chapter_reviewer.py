from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from collections.abc import Callable
from datetime import datetime, timezone

from anthropic import Anthropic

from app.config import settings
from app.models.schemas import (
    AIChapterReviewResult,
    BookPlan,
    ChapterCompletenessResult,
    ChapterPlan,
    KnowledgeBase,
    PlotBeatReview,
)
from app.services.chapter_quality import (
    sentence_is_complete,
    truncate_to_complete_sentence,
)
from app.services.model_response_parser import (
    extract_model_text,
    parse_model_json_response,
)


ProgressCallback = Callable[[float, str, str], None]


@dataclass(frozen=True)
class QualityCheckResponse:
    structured_report: dict | None
    readable_report: str
    raw_response: str
    parse_warning: str | None


def parse_quality_check_response(raw_response) -> QualityCheckResponse:
    if isinstance(raw_response, dict) and _looks_like_quality_report(raw_response):
        raw_text = json.dumps(raw_response, ensure_ascii=False)
        return QualityCheckResponse(
            structured_report=raw_response,
            readable_report="",
            raw_response=raw_text,
            parse_warning=None,
        )
    payload, visible_text, parse_error = parse_model_json_response(raw_response)
    reasoning_text = _extract_reasoning_text(raw_response)
    raw_text = "\n\n".join(
        part for part in (visible_text.strip(), reasoning_text.strip()) if part
    ).strip()
    if payload is not None:
        return QualityCheckResponse(
            structured_report=payload,
            readable_report=_readable_part(visible_text),
            raw_response=raw_text or visible_text,
            parse_warning=None,
        )

    readable = visible_text.strip() or reasoning_text.strip()
    return QualityCheckResponse(
        structured_report=None,
        readable_report=readable,
        raw_response=raw_text,
        parse_warning=(
            "AI 质检返回了非 JSON 格式，已按文本报告展示"
            if readable
            else parse_error or "AI 质检没有返回任何可用文本"
        ),
    )


def _looks_like_quality_report(value: dict) -> bool:
    quality_keys = {
        "overall_pass",
        "score",
        "summary_alignment",
        "plot_beats_coverage",
        "ending_state_alignment",
        "problems",
        "repair_suggestions",
    }
    wrapper_keys = {"content", "choices", "message", "output_text"}
    return bool(quality_keys.intersection(value)) and not wrapper_keys.intersection(value)


class ChapterReviewService:
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

    async def review(
        self,
        *,
        generation_id: str,
        content: str,
        plan: ChapterPlan,
        book_plan: BookPlan | None,
        previous_chapter_tail: str,
        next_plan: ChapterPlan | None,
        knowledge_base: KnowledgeBase,
        rule_check: ChapterCompletenessResult,
        progress_callback: ProgressCallback | None = None,
    ) -> AIChapterReviewResult:
        self._require_client()
        if progress_callback:
            progress_callback(15, "正在准备审稿材料", "正在整理章节规划和前后章上下文")
        prompt = self._review_prompt(
            content=content,
            plan=plan,
            book_plan=book_plan,
            previous_chapter_tail=previous_chapter_tail,
            next_plan=next_plan,
            knowledge_base=knowledge_base,
            rule_check=rule_check,
        )
        prompt = _limit_prompt(prompt, settings.chapter_review_prompt_max_chars)
        if progress_callback:
            progress_callback(
                35,
                "正在调用 AI 深度质检",
                f"质检 Prompt 字符数：{len(prompt)}",
            )
        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._client.messages.create,
                model=settings.anthropic_model,
                max_tokens=min(
                    settings.anthropic_max_tokens,
                    settings.chapter_review_max_tokens,
                ),
                system=(
                    "你是严谨的长篇小说责任编辑。请输出用户可直接阅读的 Markdown 审稿报告；"
                    "依据语义、因果、人物行为和叙事功能判断，不得只做关键词匹配。"
                ),
                messages=[{"role": "user", "content": prompt}],
                timeout=settings.chapter_review_timeout_seconds,
            ),
            timeout=settings.chapter_review_timeout_seconds,
        )
        if progress_callback:
            progress_callback(82, "正在解析质检报告", "模型已返回，正在校验结构化结论")
        parsed = parse_quality_check_response(response)
        if parsed.structured_report is not None:
            report = _normalize_review(
                parsed.structured_report,
                plan=plan,
                generation_id=generation_id,
                prompt_chars=len(prompt),
            )
            report.semantic_overrides = _semantic_overrides(rule_check, report)
            report.readable_report = parsed.readable_report
            report.raw_response = parsed.raw_response
        elif parsed.readable_report:
            report = AIChapterReviewResult(
                plan_id=plan.plan_id,
                generation_id=generation_id,
                report_format="text",
                readable_report=parsed.readable_report,
                raw_response=parsed.raw_response,
                parse_warning=parsed.parse_warning or "",
                model_name=settings.anthropic_model,
                prompt_chars=len(prompt),
                reviewed_at=datetime.now(timezone.utc),
            )
        else:
            raise ValueError(parsed.parse_warning or "AI 质检没有返回任何可用文本")
        return report

    async def repair(
        self,
        *,
        content: str,
        plan: ChapterPlan,
        review: AIChapterReviewResult,
        previous_chapter_tail: str,
        next_plan: ChapterPlan | None,
        book_plan: BookPlan | None,
        knowledge_base: KnowledgeBase,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        self._require_client()
        if progress_callback:
            progress_callback(15, "正在准备修复", "正在把质检问题转换为最小修改要求")
        prompt = self._repair_prompt(
            content=content,
            plan=plan,
            review=review,
            previous_chapter_tail=previous_chapter_tail,
            next_plan=next_plan,
            book_plan=book_plan,
            knowledge_base=knowledge_base,
        )
        prompt = _limit_prompt(prompt, settings.chapter_review_prompt_max_chars)
        if progress_callback:
            progress_callback(
                38,
                "正在根据质检修复",
                f"修复 Prompt 字符数：{len(prompt)}",
            )
        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._client.messages.create,
                model=settings.anthropic_model,
                max_tokens=min(
                    settings.anthropic_max_tokens,
                    settings.chapter_repair_max_tokens,
                ),
                system=(
                    "你是小说责任编辑。保留原文优点，只修复质检指出的问题。"
                    "只输出修复后的完整章节正文，不要解释，不要 Markdown 代码块。"
                ),
                messages=[{"role": "user", "content": prompt}],
                timeout=settings.chapter_review_timeout_seconds,
            ),
            timeout=settings.chapter_review_timeout_seconds,
        )
        repaired = _clean_repaired_text(extract_model_text(response))
        if not repaired:
            raise ValueError("AI 修复返回了空正文")
        maximum = min(10_000, max(8000, int(plan.target_words * 1.5)))
        repaired = _trim_to_word_limit(repaired, maximum)
        if len("".join(repaired.split())) < max(
            600,
            int(len("".join(content.split())) * 0.6),
        ):
            raise ValueError("AI 修复结果明显短于原文，已保留原稿")
        if not sentence_is_complete(repaired):
            raise ValueError("AI 修复结果末句仍不完整，已保留原稿")
        if progress_callback:
            progress_callback(88, "正在重新检查", "修复正文已返回，正在运行规则完整性检查")
        return repaired

    def _require_client(self) -> None:
        if self._client is None:
            raise ValueError("未配置 API Key，无法执行 AI 深度质检")

    @staticmethod
    def _review_prompt(
        *,
        content: str,
        plan: ChapterPlan,
        book_plan: BookPlan | None,
        previous_chapter_tail: str,
        next_plan: ChapterPlan | None,
        knowledge_base: KnowledgeBase,
        rule_check: ChapterCompletenessResult,
    ) -> str:
        expected_beats = json.dumps(plan.plot_beats, ensure_ascii=False)
        rule_issues = json.dumps(
            [item.model_dump(mode="json") for item in rule_check.issues],
            ensure_ascii=False,
        )
        schema = {
            "overall_pass": True,
            "score": 85,
            "summary_alignment": "说明是否在语义上符合本章摘要",
            "summary_aligned": True,
            "plot_beats_coverage": [
                {
                    "beat": "原规划情节点",
                    "covered": True,
                    "evidence": "不超过80字的正文依据",
                    "comment": "语义判断说明",
                }
            ],
            "ending_state_alignment": "是否达到规划结尾状态",
            "ending_state_aligned": True,
            "continuity_with_previous": "是否自然承接上一章",
            "continuity_previous_pass": True,
            "continuity_with_next": "是否能引出下一章",
            "continuity_next_pass": True,
            "character_consistency": "人物动机、语言和状态是否一致",
            "character_consistent": True,
            "style_consistency": "文风和节奏是否符合规则",
            "style_consistent": True,
            "problems": [],
            "repair_suggestions": [],
            "need_repair": False,
        }
        return f"""
请对下面章节做语义级深度审稿。不要把“没有出现相同关键词”等同于未覆盖；
隐喻、同义表达、动作结果和含蓄伏笔都可以构成覆盖，但必须给出正文依据。

## 全书总体构想摘要
{_book_summary(book_plan)}

## 当前章节规划
标题：{plan.title}
摘要：{plan.chapter_summary}
目标：{plan.chapter_goal}
作用：{"；".join(plan.chapter_function)}
开头状态：{plan.opening_state}
结尾状态：{plan.ending_state}
承接上一章：{plan.previous_bridge}
引出下一章：{plan.next_bridge}
主要冲突：{plan.conflict}
情节点：{expected_beats}
人物：{"、".join(plan.characters)}
情绪基调：{plan.emotional_tone}
章末钩子：{plan.ending_hook}

## 上一章正式正文结尾
{previous_chapter_tail or "暂无上一章正式正文，请按原著锚点和本章 opening_state 判断。"}

## 下一章规划摘要
{_next_summary(next_plan)}

## 风格与人物规则
{_style_summary(knowledge_base)}

## 现有规则检查
{rule_issues}

## 当前章节正文
{_sample_content(content, 9000)}

## 输出要求
优先返回下面格式的 Markdown 报告，不要只输出内部推理：

# AI 深度质检报告
## 总体结论
通过 / 有提醒 / 建议修改 / 不建议保存
## 评分
0-100 分
## 与章节规划的符合度
说明本章是否符合章节规划。
## 情节点覆盖
逐条说明规划情节点是否覆盖，并给出正文依据。
## 前后章节衔接
说明是否承接上一章、是否能引出下一章。
## 人物一致性
说明人物行为、语气、动机是否稳定。
## 风格一致性
说明是否贴近已有文风。
## 主要问题
列出问题。
## 修改建议
给出具体修改建议。
## 是否建议保存
建议保存 / 建议小修后保存 / 建议重写。

如果方便，可以在 Markdown 后附带下面结构的 JSON；JSON 不是唯一有效结果：
{json.dumps(schema, ensure_ascii=False)}
""".strip()

    @staticmethod
    def _repair_prompt(
        *,
        content: str,
        plan: ChapterPlan,
        review: AIChapterReviewResult,
        previous_chapter_tail: str,
        next_plan: ChapterPlan | None,
        book_plan: BookPlan | None,
        knowledge_base: KnowledgeBase,
    ) -> str:
        review_payload = review.model_dump(
            mode="json",
            exclude={
                "semantic_overrides",
                "model_name",
                "prompt_chars",
                "reviewed_at",
            },
        )
        return f"""
请根据质检报告对章节做最小必要修复，并输出修复后的完整章节正文。

修复原则：
- 保留原文已有优点、叙事声音、有效场景和人物对白；
- 不要大幅重写整章，除非质检明确判定严重偏离；
- 优先补足缺失情节点、修复前后章衔接、强化 ending_state 和 next_bridge；
- 不要机械塞入规划原句或关键词；
- 不得缩写成摘要，不得解释修改过程；
- 最后一句必须完整并以正常中文结束标点收尾。

## 全书摘要
{_book_summary(book_plan)}

## 本章规划
标题：{plan.title}
摘要：{plan.chapter_summary}
目标：{plan.chapter_goal}
建议字数：{plan.target_words} 字；合理上限：{min(10_000, max(8000, int(plan.target_words * 1.5)))} 字
情节点：{"；".join(plan.plot_beats)}
开头状态：{plan.opening_state}
结尾状态：{plan.ending_state}
前章衔接：{plan.previous_bridge}
后章衔接：{plan.next_bridge}
人物：{"、".join(plan.characters)}
情绪基调：{plan.emotional_tone}

## 上一章结尾
{previous_chapter_tail or "暂无上一章正式正文"}

## 下一章摘要
{_next_summary(next_plan)}

## 风格规则
{_style_summary(knowledge_base)}

## AI 质检报告
{json.dumps(review_payload, ensure_ascii=False)}

## 原始正文
{content}
""".strip()


def _normalize_review(
    payload: dict,
    *,
    plan: ChapterPlan,
    generation_id: str,
    prompt_chars: int,
) -> AIChapterReviewResult:
    raw_beats = payload.get("plot_beats_coverage")
    beat_values = raw_beats if isinstance(raw_beats, list) else []
    by_beat = {
        _text(item.get("beat")): item
        for item in beat_values
        if isinstance(item, dict) and _text(item.get("beat"))
    }
    beats: list[PlotBeatReview] = []
    for index, beat in enumerate(plan.plot_beats):
        raw = by_beat.get(beat)
        if raw is None and index < len(beat_values) and isinstance(beat_values[index], dict):
            raw = beat_values[index]
        raw = raw or {}
        beats.append(
            PlotBeatReview(
                beat=beat,
                covered=_boolean(raw.get("covered")),
                evidence=_text(raw.get("evidence"))[:300],
                comment=_text(raw.get("comment"))[:500],
            )
        )
    try:
        score = int(payload.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    need_repair = _boolean(payload.get("need_repair"))
    overall_pass = _boolean(payload.get("overall_pass"))
    if "overall_pass" not in payload:
        overall_pass = score >= 70 and not need_repair
    return AIChapterReviewResult(
        plan_id=plan.plan_id,
        generation_id=generation_id,
        overall_pass=overall_pass,
        score=score,
        summary_alignment=_text(payload.get("summary_alignment")),
        summary_aligned=_boolean(payload.get("summary_aligned")),
        plot_beats_coverage=beats,
        ending_state_alignment=_text(payload.get("ending_state_alignment")),
        ending_state_aligned=_boolean(payload.get("ending_state_aligned")),
        continuity_with_previous=_text(payload.get("continuity_with_previous")),
        continuity_previous_pass=_boolean(payload.get("continuity_previous_pass")),
        continuity_with_next=_text(payload.get("continuity_with_next")),
        continuity_next_pass=_boolean(payload.get("continuity_next_pass")),
        character_consistency=_text(payload.get("character_consistency")),
        character_consistent=_boolean(payload.get("character_consistent")),
        style_consistency=_text(payload.get("style_consistency")),
        style_consistent=_boolean(payload.get("style_consistent")),
        problems=_string_list(payload.get("problems")),
        repair_suggestions=_string_list(payload.get("repair_suggestions")),
        need_repair=need_repair,
        model_name=settings.anthropic_model,
        prompt_chars=prompt_chars,
        reviewed_at=datetime.now(timezone.utc),
    )


def _extract_reasoning_text(raw_response) -> str:
    parts: list[str] = []
    seen: set[int] = set()

    def visit(value) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
            return

        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)

        if isinstance(value, dict):
            for key in ("reasoning_content", "thinking", "reasoning"):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            for key in ("content", "message", "choices"):
                if key in value:
                    visit(value[key])
            return

        for attribute in ("reasoning_content", "thinking", "reasoning"):
            text = getattr(value, attribute, None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        for attribute in ("content", "message", "choices"):
            nested = getattr(value, attribute, None)
            if nested is not None:
                visit(nested)

    visit(raw_response)
    return "\n\n".join(dict.fromkeys(parts)).strip()


def _readable_part(text: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    clean = re.sub(
        r"```(?:json)?\s*\{.*?\}\s*```",
        "",
        clean,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    if clean.startswith("{") and clean.endswith("}"):
        return ""
    return clean


def _semantic_overrides(
    rule_check: ChapterCompletenessResult,
    review: AIChapterReviewResult,
) -> list[str]:
    codes = {item.code for item in rule_check.issues}
    values: list[str] = []
    if "summary_alignment" in codes and review.summary_aligned:
        values.append("规则检查提示摘要关键词覆盖偏低，但 AI 质检认为语义上已覆盖。")
    if "ending_state" in codes and review.ending_state_aligned:
        values.append("规则检查未命中结尾状态关键词，但 AI 质检认为结尾语义已达到规划状态。")
    if "next_bridge" in codes and review.continuity_next_pass:
        values.append("规则检查未命中下一章衔接关键词，但 AI 质检认为已形成自然引导。")
    if "plot_beat_coverage" in codes and review.plot_beats_coverage:
        if all(item.covered for item in review.plot_beats_coverage):
            values.append("规则检查提示情节点关键词覆盖偏低，但 AI 质检认为各情节点均已语义覆盖。")
    return values


def _book_summary(book_plan: BookPlan | None) -> str:
    if book_plan is None:
        return "暂无全书总体构想。"
    return (
        f"书名：{book_plan.title}\n"
        f"故事：{book_plan.premise[:1200]}\n"
        f"主线冲突：{book_plan.main_conflict[:800]}\n"
        f"主题：{book_plan.core_theme[:500]}\n"
        f"结尾方向：{book_plan.ending_direction[:800]}\n"
        f"基调：{book_plan.tone[:400]}"
    )


def _next_summary(next_plan: ChapterPlan | None) -> str:
    if next_plan is None:
        return "这是终章或暂无下一章规划。"
    return (
        f"第 {next_plan.order} 章《{next_plan.title}》："
        f"{(next_plan.chapter_summary or next_plan.chapter_goal)[:1000]}"
    )


def _style_summary(knowledge_base: KnowledgeBase) -> str:
    style = knowledge_base.style_knowledge
    parts: list[str] = []
    if style:
        parts.extend(
            [
                style.global_narrative_style,
                style.global_language_style,
                style.global_pacing_pattern,
                "人物规则：" + "；".join(style.global_character_rules[:5]),
                "对话规则：" + "；".join(style.global_dialogue_rules[:5]),
                "禁写：" + "；".join(style.do_not_write_list[:5]),
            ]
        )
    if knowledge_base.characters:
        parts.append(
            "人物：" + "；".join(
                f"{item.name}（{item.personality[:120]}，语言：{item.speech_style[:100]}）"
                for item in knowledge_base.characters[:8]
            )
        )
    return "\n".join(item for item in parts if item.strip()) or "沿用当前章节规划中的人物和情绪规则。"


def _sample_content(content: str, limit: int) -> str:
    clean = content.strip()
    if len(clean) <= limit:
        return clean
    first = int(limit * 0.4)
    middle = int(limit * 0.2)
    last = limit - first - middle
    center = max(0, len(clean) // 2 - middle // 2)
    return (
        clean[:first]
        + "\n\n[正文中段抽样]\n\n"
        + clean[center:center + middle]
        + "\n\n[正文结尾]\n\n"
        + clean[-last:]
    )


def _limit_prompt(prompt: str, limit: int) -> str:
    if len(prompt) <= limit:
        return prompt
    marker = "\n\n[提示词过长，已保留规划、正文开头和结尾]\n\n"
    keep = limit - len(marker)
    return prompt[: int(keep * 0.62)] + marker + prompt[-int(keep * 0.38):]


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _text(value).lower() in {"true", "yes", "1", "是", "通过", "已覆盖"}


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_text(item) for item in value if _text(item)]
    if isinstance(value, dict):
        return [f"{key}：{item}" for key, item in value.items()]
    text = _text(value)
    return [text] if text else []


def _clean_repaired_text(text: str) -> str:
    clean = text.strip()
    match = re.fullmatch(r"```(?:text|markdown)?\s*(.*?)```", clean, re.DOTALL | re.IGNORECASE)
    if match:
        clean = match.group(1).strip()
    return clean


def _trim_to_word_limit(text: str, limit: int) -> str:
    if len("".join(text.split())) <= limit:
        return text
    count = 0
    cut = len(text)
    for index, character in enumerate(text):
        if not character.isspace():
            count += 1
        if count >= limit:
            cut = index + 1
            break
    prefix = text[:cut].rstrip()
    complete = truncate_to_complete_sentence(prefix)
    return complete if complete else prefix
