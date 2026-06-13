import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# 显式加载 backend/.env
_ENV_FILE = Path(__file__).parent.parent / ".env"
ENV_LOADED = _ENV_FILE.exists() and load_dotenv(_ENV_FILE, override=False)


def _get_api_key() -> str:
    """按优先级读取 API Key"""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY"):
        val = os.getenv(var, "")
        if val:
            return val
    return ""


def _get_base_url() -> str:
    """按优先级读取 Base URL"""
    for var in ("ANTHROPIC_BASE_URL", "DEEPSEEK_BASE_URL"):
        val = os.getenv(var, "")
        if val:
            return val
    return "https://api.deepseek.com/anthropic"


def _get_model() -> str:
    return os.getenv("ANTHROPIC_MODEL", "").strip() or "deepseek-v4-pro[1m]"


class Settings(BaseSettings):
    # ── API 配置 ──
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "deepseek-v4-pro[1m]"
    anthropic_max_tokens: int = 8192
    anthropic_thinking_budget: int = 4096
    model_timeout_seconds: float = 60.0
    generation_timeout_seconds: float = 180.0
    generation_max_tokens: int = 1200
    generation_segment_max_tokens: int = 1400
    generation_segment_target_words: int = 700
    generation_prompt_max_chars: int = 7000
    generation_draft_tail_chars: int = 2200
    chapter_review_timeout_seconds: float = 180.0
    chapter_review_max_tokens: int = 6000
    chapter_review_prompt_max_chars: int = 16000
    chapter_repair_max_tokens: int = 7000
    book_plan_timeout_seconds: float = 180.0
    book_plan_max_tokens: int = 3600
    book_plan_prompt_max_chars: int = 14000
    style_model_max_tokens: int = 1800
    style_prompt_max_chars: int = 12000
    style_prompt_max_input_tokens: int = 10000
    style_summary_prompt_max_chars: int = 18000
    style_summary_max_input_tokens: int = 16000
    style_chapter_sample_chars: int = 9000
    style_chapter_retries: int = 2

    # ── 数据路径 ──
    data_dir: Path = Path(__file__).parent.parent / "data"
    raw_dir: Path = data_dir / "raw"
    processed_dir: Path = data_dir / "processed"
    analysis_dir: Path = data_dir / "analysis"
    style_cache_dir: Path = data_dir / "style_cache"
    style_cache_novel_id: str = "longzu"
    continuation_project_dir: Path = data_dir / "projects" / "longzu_continuation"
    writing_project_dir: Path = (
        Path(__file__).resolve().parents[2] / "writing_projects" / "longzu6"
    )

    max_chapter_length: int = 20000

    model_config = {"extra": "ignore"}


settings = Settings()
# 覆盖从 .env 直接读取的值（不受 pydantic-settings prefix 限制）
settings.anthropic_api_key = _get_api_key()
settings.anthropic_base_url = _get_base_url()
settings.anthropic_model = _get_model()
