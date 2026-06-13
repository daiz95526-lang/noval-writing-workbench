from __future__ import annotations

import json
import re
from typing import Any


_THINKING_TYPES = {"thinking", "redacted_thinking", "reasoning"}


def extract_model_text(raw_response: Any) -> str:
    """Extract user-visible text while ignoring provider thinking blocks."""
    parts: list[str] = []
    seen: set[int] = set()

    def visit(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            if value.strip():
                parts.append(value)
            return
        if isinstance(value, bytes):
            visit(value.decode("utf-8", errors="replace"))
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
            block_type = str(value.get("type") or "").lower()
            if block_type in _THINKING_TYPES:
                return
            if isinstance(value.get("text"), str):
                visit(value["text"])
                return
            for key in ("content", "output_text", "message", "choices"):
                if key in value:
                    visit(value[key])
            return

        block_type = str(getattr(value, "type", "") or "").lower()
        if block_type in _THINKING_TYPES:
            return
        text = getattr(value, "text", None)
        if isinstance(text, str):
            visit(text)
            return
        for attribute in ("content", "output_text", "message", "choices"):
            nested = getattr(value, attribute, None)
            if nested is not None:
                visit(nested)

    visit(raw_response)
    return "\n".join(part.strip() for part in parts if part.strip()).strip()


def parse_model_json_response(
    raw_response: Any,
) -> tuple[dict | None, str, str | None]:
    """
    Return parsed JSON, extracted visible text, and a parse error.

    The parser accepts provider response objects, text blocks, Markdown fences,
    surrounding prose, BOMs, trailing commas, and safely repairable smart quotes.
    """
    if isinstance(raw_response, dict) and _looks_like_payload(raw_response):
        return raw_response, json.dumps(raw_response, ensure_ascii=False), None

    extracted_text = extract_model_text(raw_response).lstrip("\ufeff").strip()
    if not extracted_text:
        return None, "", "模型响应中没有可解析的文本内容"

    candidates: list[str] = [extracted_text]
    candidates.extend(
        match.group(1)
        for match in re.finditer(
            r"```(?:json)?\s*(.*?)```",
            extracted_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    candidates.extend(_balanced_json_objects(extracted_text))

    errors: list[tuple[int, str]] = []
    checked: set[str] = set()
    for candidate in candidates:
        for repaired in _repair_candidates(candidate):
            if not repaired or repaired in checked:
                continue
            checked.add(repaired)
            try:
                value = json.loads(repaired, strict=False)
            except json.JSONDecodeError as exc:
                errors.append((exc.pos, str(exc)))
                continue
            except TypeError as exc:
                errors.append((0, str(exc)))
                continue
            if isinstance(value, dict):
                return value, extracted_text, None
            errors.append(
                (0, f"JSON 顶层类型为 {type(value).__name__}，需要 object")
            )

    detail = max(errors, key=lambda item: item[0])[1] if errors else "未找到完整 JSON 对象"
    return None, extracted_text, f"模型返回文本 JSON 解析失败：{detail}"


def _looks_like_payload(value: dict) -> bool:
    wrapper_keys = {"content", "choices", "message", "output_text"}
    plan_keys = {
        "title",
        "premise",
        "chapters",
        "main_conflict",
        "core_theme",
    }
    return bool(plan_keys.intersection(value)) and not wrapper_keys.intersection(value)


def _balanced_json_objects(text: str) -> list[str]:
    values: list[str] = []
    start = -1
    depth = 0
    in_string = False
    escaped = False

    for index, character in enumerate(text):
        if start < 0:
            if character == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                values.append(text[start:index + 1])
                start = -1
    return values


def _repair_candidates(candidate: str) -> list[str]:
    value = candidate.strip().lstrip("\ufeff").strip()
    value = re.sub(r"^\s*json\s*", "", value, flags=re.IGNORECASE)
    variants = [value]

    without_trailing_commas = re.sub(r",\s*([}\]])", r"\1", value)
    variants.append(without_trailing_commas)
    truncated = _close_truncated_json(value)
    if truncated != value:
        variants.append(truncated)

    smart_quotes = value.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "＂": '"',
                "‘": "'",
                "’": "'",
            }
        )
    )
    if smart_quotes != value:
        variants.append(smart_quotes)
        variants.append(re.sub(r",\s*([}\]])", r"\1", smart_quotes))
        smart_truncated = _close_truncated_json(smart_quotes)
        if smart_truncated != smart_quotes:
            variants.append(smart_truncated)
    return variants


def _close_truncated_json(value: str) -> str:
    """Close only clearly unfinished JSON strings and containers."""
    if not value.lstrip().startswith("{"):
        return value
    stack: list[str] = []
    in_string = False
    escaped = False

    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append(character)
        elif character == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif character == "]" and stack and stack[-1] == "[":
            stack.pop()

    if not stack and not in_string:
        return value
    repaired = value.rstrip()
    if in_string:
        if escaped:
            repaired += "\\"
        repaired += '"'
    repaired = re.sub(r",\s*$", "", repaired)
    if repaired.rstrip().endswith(":"):
        repaired += " null"
    repaired += "".join("}" if item == "{" else "]" for item in reversed(stack))
    return repaired
