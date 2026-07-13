"""Generate the chapter completeness audit for the canonical corpus."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from app.models.schemas import Chapter
from app.services.file_ops import atomic_write_json, atomic_write_text
from app.services.project_profile import get_project_profile
from app.services.local_importer import read_text_with_encoding
from app.services.preprocessor import TextPreprocessor

_SHORT_CHAPTER = 500
_LONG_CHAPTER = 50_000


def _chinese_number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    total = 0
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in units:
            unit = units[char]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    return total + current


def _title_number(title: str) -> int | None:
    match = re.search(r"第([一二三四五六七八九十百千\d]+)[章节幕回]", title)
    return _chinese_number(match.group(1)) if match else None


def _sequence_issues(chapters: list[Chapter]) -> list[str]:
    numbers = [number for chapter in chapters if (number := _title_number(chapter.title))]
    issues: list[str] = []
    for previous, current in zip(numbers, numbers[1:]):
        if current == previous:
            issues.append(f"标题编号重复：第 {current} 章/幕")
        elif current > previous + 1:
            missing = ", ".join(str(n) for n in range(previous + 1, current))
            issues.append(f"标题编号缺失：{missing}")
        elif current < previous:
            issues.append(f"标题编号倒序：{previous} -> {current}")
    return list(dict.fromkeys(issues))


def generate_chapter_audit(
    *,
    source_dir: Path,
    imported_chapters: list[Chapter],
    output_dir: Path | None = None,
) -> dict:
    preprocessor = TextPreprocessor()
    files = sorted(source_dir.glob("*.txt"))
    imported_by_file: dict[str, list[Chapter]] = defaultdict(list)
    for chapter in imported_chapters:
        imported_by_file[chapter.source_file].append(chapter)

    parsed_by_file: dict[str, list[Chapter]] = {}
    file_reports: list[dict] = []
    all_parsed: list[Chapter] = []

    for file_path in files:
        raw_text, encoding = read_text_with_encoding(file_path)
        parsed = preprocessor.process(raw_text, file_path.stem)
        parsed_by_file[file_path.name] = parsed
        all_parsed.extend(parsed)
        sequence_issues = _sequence_issues(parsed)
        file_reports.append(
            {
                "filename": file_path.name,
                "exists": True,
                "size_bytes": file_path.stat().st_size,
                "encoding": encoding,
                "chapters_split": len(parsed),
                "chapters_imported": len(imported_by_file[file_path.name]),
                "total_words": sum(chapter.word_count for chapter in parsed),
                "first_title": parsed[0].title if parsed else "",
                "last_title": parsed[-1].title if parsed else "",
                "has_anomalies": bool(sequence_issues),
                "anomalies": sequence_issues,
            }
        )

    hash_counts = Counter(chapter.content_hash for chapter in all_parsed)
    duplicate_chapters = [
        {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "source_file": chapter.source_file,
        }
        for chapter in all_parsed
        if hash_counts[chapter.content_hash] > 1
    ]
    empty_chapters = [
        chapter.chapter_id for chapter in all_parsed if not chapter.content.strip()
    ]
    short_chapters = [
        {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "word_count": chapter.word_count,
        }
        for chapter in all_parsed
        if 0 < chapter.word_count < _SHORT_CHAPTER
    ]
    long_chapters = [
        {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "word_count": chapter.word_count,
        }
        for chapter in all_parsed
        if chapter.word_count > _LONG_CHAPTER
    ]
    possible_mis_splits = [
        {
            "source_file": report["filename"],
            "issue": issue,
        }
        for report in file_reports
        for issue in report["anomalies"]
    ]

    expected_files = sorted(
        f"{key}.txt" for key in TextPreprocessor.VOLUME_DISPLAY_MAP
    )
    found_names = {path.name for path in files}
    missing_files = [name for name in expected_files if name not in found_names]
    volume_status = {}
    for volume_key, (display_name, _series_order, _sub_order) in (
        TextPreprocessor.VOLUME_DISPLAY_MAP.items()
    ):
        report = next(
            (item for item in file_reports if item["filename"] == f"{volume_key}.txt"),
            None,
        )
        volume_status[display_name] = {
            "exists": report is not None,
            "chapters_split": report["chapters_split"] if report else 0,
            "chapters_imported": report["chapters_imported"] if report else 0,
            "needs_manual_review": bool(report and report["has_anomalies"]),
        }

    needs_review = [
        name
        for name, status in volume_status.items()
        if not status["exists"] or status["needs_manual_review"]
    ]
    complete = not missing_files and not possible_mis_splits and not duplicate_chapters
    report = {
        "generated_at": datetime.now().isoformat(),
        "source_dir": str(source_dir),
        "expected_files": expected_files,
        "missing_files": missing_files,
        "total_files": len(files),
        "total_chapters_split": len(all_parsed),
        "total_chapters_imported": len(imported_chapters),
        "total_words": sum(chapter.word_count for chapter in imported_chapters),
        "files": file_reports,
        "volume_status": volume_status,
        "duplicate_chapters": duplicate_chapters,
        "empty_chapters": empty_chapters,
        "short_chapters": short_chapters,
        "long_chapters": long_chapters,
        "possible_mis_splits": possible_mis_splits,
        "conclusion": {
            "corpus_structurally_complete": complete,
            "suitable_for_style_analysis": bool(imported_chapters),
            "suitable_for_generation": bool(imported_chapters),
            "manual_review_required": needs_review,
            "note": (
                "8 个源文件均可导入，但自动审计只能确认文件与章节结构，"
                "不能证明原始小说文本无删节。存在编号缺失或重复的卷需人工复核。"
            ),
        },
    }

    report_dir = output_dir or source_dir.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_dir / "chapter_audit_report.json", report)
    atomic_write_text(
        report_dir / "chapter_audit_report.md",
        _render_markdown(report),
    )
    return report


def _render_markdown(report: dict) -> str:
    lines = [
        f"# {get_project_profile().title}语料章节完整性审计报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        "## 总览",
        "",
        f"- 源文件：{report['total_files']} / {len(report['expected_files'])}",
        f"- 切分章节：{report['total_chapters_split']}",
        f"- 去重后导入章节：{report['total_chapters_imported']}",
        f"- 导入总字数：{report['total_words']:,}",
        f"- 重复章节记录：{len(report['duplicate_chapters'])}",
        f"- 异常短章：{len(report['short_chapters'])}",
        f"- 异常长章：{len(report['long_chapters'])}",
        "",
        "## 文件明细",
        "",
        "| 文件 | 大小 | 编码 | 切分 | 导入 | 总字数 | 首章 | 末章 | 异常 |",
        "|---|---:|---|---:|---:|---:|---|---|---|",
    ]
    for item in report["files"]:
        anomaly = "；".join(item["anomalies"]) or "无"
        lines.append(
            f"| {item['filename']} | {item['size_bytes']:,} | {item['encoding']} | "
            f"{item['chapters_split']} | {item['chapters_imported']} | "
            f"{item['total_words']:,} | {item['first_title']} | "
            f"{item['last_title']} | {anomaly} |"
        )

    lines.extend(["", "## 重复章节", ""])
    if report["duplicate_chapters"]:
        for item in report["duplicate_chapters"]:
            lines.append(
                f"- {item['chapter_id']}（{item['source_file']}）：{item['title']}"
            )
    else:
        lines.append("- 无")

    for heading, key in (
        ("空章节", "empty_chapters"),
        ("异常短章节", "short_chapters"),
        ("异常长章节", "long_chapters"),
        ("可能误切或缺章", "possible_mis_splits"),
    ):
        lines.extend(["", f"## {heading}", ""])
        items = report[key]
        if not items:
            lines.append("- 无")
        else:
            for item in items:
                lines.append(f"- {json.dumps(item, ensure_ascii=False)}")

    conclusion = report["conclusion"]
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"- 当前语料结构完整：{'是' if conclusion['corpus_structurally_complete'] else '否'}",
            f"- 适合风格分析：{'是' if conclusion['suitable_for_style_analysis'] else '否'}",
            f"- 适合续写生成：{'是' if conclusion['suitable_for_generation'] else '否'}",
            "- 需要人工复核：" + (
                "、".join(conclusion["manual_review_required"]) or "无"
            ),
            f"- 说明：{conclusion['note']}",
            "",
        ]
    )
    return "\n".join(lines)
