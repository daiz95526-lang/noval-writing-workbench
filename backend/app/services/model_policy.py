from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class ModelCallPolicy:
    operation: str
    timeout_seconds: float
    max_retries: int
    max_tokens: int
    prompt_max_chars: int


def get_model_policy(operation: str) -> ModelCallPolicy:
    policies = {
        "generation": ModelCallPolicy(
            operation="generation",
            timeout_seconds=settings.generation_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens=settings.generation_segment_max_tokens,
            prompt_max_chars=settings.generation_prompt_max_chars,
        ),
        "book_plan": ModelCallPolicy(
            operation="book_plan",
            timeout_seconds=settings.book_plan_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens=settings.book_plan_max_tokens,
            prompt_max_chars=settings.book_plan_prompt_max_chars,
        ),
        "chapter_review": ModelCallPolicy(
            operation="chapter_review",
            timeout_seconds=settings.chapter_review_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens=settings.chapter_review_max_tokens,
            prompt_max_chars=settings.chapter_review_prompt_max_chars,
        ),
        "style_analysis": ModelCallPolicy(
            operation="style_analysis",
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens=settings.style_model_max_tokens,
            prompt_max_chars=settings.style_prompt_max_chars,
        ),
        "knowledge_build": ModelCallPolicy(
            operation="knowledge_build",
            timeout_seconds=settings.model_timeout_seconds,
            max_retries=settings.model_max_retries,
            max_tokens=settings.anthropic_max_tokens,
            prompt_max_chars=settings.style_summary_prompt_max_chars,
        ),
    }
    try:
        return policies[operation]
    except KeyError as exc:
        raise ValueError(f"未知模型调用类型: {operation}") from exc


def anthropic_client_options(operation: str) -> dict[str, float | int]:
    policy = get_model_policy(operation)
    return {
        "max_retries": policy.max_retries,
        "timeout": policy.timeout_seconds,
    }


def bounded_prompt(value: str, operation: str) -> str:
    policy = get_model_policy(operation)
    return value[: policy.prompt_max_chars]
