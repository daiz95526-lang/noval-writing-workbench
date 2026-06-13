from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.schemas import (
    ChapterCompletenessResult,
    ChapterPlan,
    ContinuityIssue,
)


_COMPLETE_ENDINGS = ("。", "！", "？", "……", "”", "’", "」", "』", "）")
_BAD_ENDINGS = ("，", "、", "：", "；", "—", "-", "…", "（", "(", "“", "‘", "「", "『")
_BAD_TAIL_WORDS = (
    "我是",
    "因为",
    "然后",
    "但是",
    "他说",
    "她说",
    "所以",
    "如果",
    "而且",
    "只是",
)
_SENTENCE_BOUNDARY = re.compile(r"(?:……|[。！？](?:[”’」』）]+)?|[”’」』）])")


@dataclass(frozen=True)
class EndingResolution:
    text: str
    status: str
    warning: str | None = None


def sentence_is_complete(text: str) -> bool:
    clean = text.rstrip()
    if not clean or clean.endswith(_BAD_ENDINGS):
        return False
    if any(clean.endswith(word) for word in _BAD_TAIL_WORDS):
        return False
    if clean.count("“") > clean.count("”"):
        return False
    if clean.count("‘") > clean.count("’"):
        return False
    if clean.count("「") > clean.count("」"):
        return False
    if clean.count("『") > clean.count("』"):
        return False
    if clean.count("（") > clean.count("）"):
        return False
    return clean.endswith(_COMPLETE_ENDINGS)


def truncate_to_complete_sentence(text: str) -> str:
    clean = text.rstrip()
    matches = list(_SENTENCE_BOUNDARY.finditer(clean))
    if matches:
        return clean[:matches[-1].end()].rstrip()

    paragraphs = [
        match
        for match in re.finditer(r"(?:^|\n\s*\n|\n)([^\n]+)", clean)
        if match.group(1).strip()
    ]
    if len(paragraphs) > 1:
        previous = clean[:paragraphs[-1].start()].rstrip()
        if previous:
            return previous
    return clean


def ensure_complete_ending(
    text: str,
    *,
    repaired_text: str = "",
    minimum_usable_chars: int = 300,
) -> EndingResolution:
    clean = text.rstrip()
    if sentence_is_complete(clean):
        return EndingResolution(clean, "ok")

    repaired = repaired_text.rstrip()
    if repaired and sentence_is_complete(repaired):
        return EndingResolution(repaired, "repaired")

    truncated = truncate_to_complete_sentence(clean)
    if truncated and truncated != clean:
        return EndingResolution(
            truncated,
            "truncated",
            "末句未完整返回，已安全截断到最后一个完整句子。",
        )

    if len("".join(clean.split())) >= minimum_usable_chars:
        return EndingResolution(
            clean,
            "partial",
            "末句可能不完整，已保留可用正文，可手动修复或继续生成。",
        )

    return EndingResolution(
        clean,
        "failed",
        "正文过短且没有可确认的完整句子边界。",
    )


def remove_duplicate_paragraphs(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    seen: set[str] = set()
    result: list[str] = []
    for paragraph in paragraphs:
        normalized = re.sub(r"\s+", "", paragraph)
        if len(normalized) >= 30 and normalized in seen:
            continue
        if len(normalized) >= 30:
            seen.add(normalized)
        if paragraph.strip():
            result.append(paragraph.strip())
    return "\n\n".join(result)


def check_chapter_completeness(
    content: str,
    plan: ChapterPlan,
) -> ChapterCompletenessResult:
    clean = content.strip()
    word_count = len("".join(clean.split()))
    minimum = max(1200, int(plan.target_words * 0.6))
    maximum = min(10_000, max(8000, int(plan.target_words * 1.5)))
    blocking_errors: list[ContinuityIssue] = []
    warnings: list[ContinuityIssue] = []
    info: list[ContinuityIssue] = [
        ContinuityIssue(
            level="info",
            code="word_count",
            message=f"正文共 {word_count} 字，建议范围 {minimum}-{maximum} 字。",
        )
    ]

    if not clean:
        blocking_errors.append(
            ContinuityIssue(
                level="error",
                code="empty_content",
                message="正文为空，不能保存为正式章节。",
            )
        )
    elif word_count < 500:
        blocking_errors.append(
            ContinuityIssue(
                level="error",
                code="chapter_too_short",
                message=f"正文仅 {word_count} 字，低于正式章节最低可用长度 500 字。",
            )
        )
    elif word_count < minimum:
        warnings.append(
            ContinuityIssue(
                level="warning",
                code="chapter_below_recommended",
                message=f"正文 {word_count} 字，低于本章建议下限 {minimum} 字，可人工确认后保存。",
            )
        )

    if word_count > maximum * 2:
        blocking_errors.append(
            ContinuityIssue(
                level="error",
                code="chapter_extremely_long",
                message=f"正文 {word_count} 字，超过建议上限 {maximum} 字的一倍以上，请拆分或精简后保存。",
            )
        )
    elif word_count > maximum:
        over_ratio = (word_count - maximum) / maximum
        warnings.append(
            ContinuityIssue(
                level="warning",
                code=(
                    "chapter_above_recommended"
                    if over_ratio <= 0.3
                    else "chapter_strongly_above_recommended"
                ),
                message=(
                    f"正文 {word_count} 字，略高于建议上限 {maximum} 字，可人工确认后保存。"
                    if over_ratio <= 0.3
                    else f"正文 {word_count} 字，明显高于建议上限 {maximum} 字，建议复核，但仍可保存。"
                ),
            )
        )

    if _looks_garbled(clean):
        blocking_errors.append(
            ContinuityIssue(
                level="error",
                code="garbled_content",
                message="正文包含大量乱码或替换字符，暂不可保存。",
            )
        )

    complete_ending = sentence_is_complete(clean)
    if complete_ending:
        info.append(
            ContinuityIssue(
                level="info",
                code="complete_ending",
                message="正文末句完整。",
            )
        )
    elif word_count < 500 or truncate_to_complete_sentence(clean) == clean:
        blocking_errors.append(
            ContinuityIssue(
                level="error",
                code="incomplete_ending",
                message="章节末句严重不完整，且没有可安全截断的完整句子。",
            )
        )
    else:
        warnings.append(
            ContinuityIssue(
                level="warning",
                code="incomplete_ending",
                message="章节末句可能不完整，但前文可用，可人工修复后保存。",
            )
        )

    normalized_paragraphs = [
        re.sub(r"\s+", "", item)
        for item in re.split(r"\n\s*\n", clean)
        if len(re.sub(r"\s+", "", item)) >= 30
    ]
    repeated = {
        paragraph
        for paragraph in normalized_paragraphs
        if normalized_paragraphs.count(paragraph) > 1
    }
    if repeated:
        warnings.append(
            ContinuityIssue(
                level="warning",
                code="duplicate_paragraphs",
                message=f"发现 {len(repeated)} 处完全重复的较长段落，请人工复核。",
            )
        )

    _append_alignment_warning(
        warnings,
        clean,
        plan.chapter_summary or plan.chapter_goal,
        "summary_alignment",
        "正文未明显覆盖本章摘要关键词，请人工检查是否偏离规划。",
    )
    ending = clean[-1200:]
    _append_alignment_warning(
        warnings,
        ending,
        plan.ending_state,
        "ending_state",
        "正文结尾未明显体现规划中的结束状态。",
    )
    _append_alignment_warning(
        warnings,
        ending,
        plan.next_bridge or plan.ending_hook,
        "next_bridge",
        "正文结尾未明显留下通往下一章的衔接。",
    )
    if plan.plot_beats:
        covered = sum(
            1
            for beat in plan.plot_beats
            if any(keyword in clean for keyword in _keywords(beat))
        )
        if covered < max(1, len(plan.plot_beats) // 2):
            warnings.append(
                ContinuityIssue(
                    level="warning",
                    code="plot_beat_coverage",
                    message="正文对规划情节点的关键词覆盖偏低，请人工复核。",
                )
            )

    passed = not blocking_errors
    issues = [*blocking_errors, *warnings, *info]
    return ChapterCompletenessResult(
        plan_id=plan.plan_id,
        passed=passed,
        can_save_official=passed,
        word_count=word_count,
        target_word_count=plan.target_words,
        minimum_word_count=minimum,
        maximum_word_count=maximum,
        sentence_complete=complete_ending,
        blocking_errors=blocking_errors,
        warnings=warnings,
        info=info,
        issues=issues,
        checked_at=datetime.now(timezone.utc),
    )


def _append_alignment_warning(
    issues: list[ContinuityIssue],
    content: str,
    expected: str,
    code: str,
    message: str,
) -> None:
    keywords = _keywords(expected)
    if keywords and not any(keyword in content for keyword in keywords):
        issues.append(
            ContinuityIssue(
                level="warning",
                code=code,
                message=message,
            )
        )


def _keywords(text: str) -> list[str]:
    values = re.split(r"[\s，。；：、,.!?！？;:（）()\[\]【】“”]+", text)
    return [value for value in values if 2 <= len(value) <= 12][:12]


def _looks_garbled(text: str) -> bool:
    if not text:
        return False
    replacement_count = text.count("\ufffd")
    mojibake_count = sum(text.count(value) for value in ("锛", "銆", "鈥", "绔", "姝"))
    return replacement_count >= 3 or mojibake_count / max(1, len(text)) > 0.03
