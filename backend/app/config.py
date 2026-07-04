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


def _get_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else default


_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
_DEFAULT_WRITING_PROJECT_DIR = (
    Path(__file__).resolve().parents[2] / "writing_projects" / "longzu6"
)


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
    data_dir: Path = _DEFAULT_DATA_DIR
    raw_dir: Path = _DEFAULT_DATA_DIR / "raw"
    processed_dir: Path = _DEFAULT_DATA_DIR / "processed"
    analysis_dir: Path = _DEFAULT_DATA_DIR / "analysis"
    style_cache_dir: Path = _DEFAULT_DATA_DIR / "style_cache"
    style_cache_novel_id: str = "longzu"
    continuation_project_dir: Path = _DEFAULT_DATA_DIR / "projects" / "longzu_continuation"
    writing_project_dir: Path = _DEFAULT_WRITING_PROJECT_DIR

    max_chapter_length: int = 20000

    model_config = {"extra": "ignore"}


settings = Settings()
# 覆盖从 .env 直接读取的值（不受 pydantic-settings prefix 限制）
settings.anthropic_api_key = _get_api_key()
settings.anthropic_base_url = _get_base_url()
settings.anthropic_model = _get_model()

# Desktop packaging can relocate all mutable data under %APPDATA%\Noval without
# changing the web development defaults.
settings.data_dir = _get_path("DATA_DIR", settings.data_dir)
settings.raw_dir = _get_path("RAW_DIR", settings.data_dir / "raw")
settings.processed_dir = _get_path("PROCESSED_DIR", settings.data_dir / "processed")
settings.analysis_dir = _get_path("ANALYSIS_DIR", settings.data_dir / "analysis")
settings.style_cache_dir = _get_path("STYLE_CACHE_DIR", settings.data_dir / "style_cache")
settings.continuation_project_dir = _get_path(
    "CONTINUATION_PROJECT_DIR",
    settings.data_dir / "projects" / "longzu_continuation",
)
settings.writing_project_dir = _get_path(
    "WRITING_PROJECT_DIR",
    settings.writing_project_dir,
)
