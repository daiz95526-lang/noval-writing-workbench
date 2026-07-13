import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"
ENV_LOADED = ENV_FILE.exists() and load_dotenv(ENV_FILE, override=False)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010
DEFAULT_FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEFAULT_PROJECT_ID = "longzu6"
DEFAULT_PROJECT_TITLE = "龙族 VI 续写工程"
DEFAULT_DATA_DIR = BACKEND_DIR / "data"
DEFAULT_PROJECTS_DIR = DEFAULT_DATA_DIR / "projects"
DEFAULT_CORPUS_SOURCE_DIR = DEFAULT_DATA_DIR / "books" / "longzu" / "source_txt"
DEFAULT_CONTINUATION_PROJECT_DIR = (
    DEFAULT_DATA_DIR / "projects" / "longzu_continuation"
)
DEFAULT_WRITING_PROJECT_DIR = PROJECT_ROOT / "writing_projects" / "longzu6"


class Settings(BaseModel):
    # API settings
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    anthropic_model: str = "deepseek-v4-pro[1m]"
    anthropic_default_haiku_model: str = "deepseek-v4-flash"
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

    # Local server settings
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    frontend_origins: tuple[str, ...] = DEFAULT_FRONTEND_ORIGINS

    # Project metadata
    project_id: str = DEFAULT_PROJECT_ID
    project_title: str = DEFAULT_PROJECT_TITLE

    # Data paths
    data_dir: Path = DEFAULT_DATA_DIR
    projects_dir: Path = DEFAULT_PROJECTS_DIR
    raw_dir: Path = DEFAULT_DATA_DIR / "raw"
    processed_dir: Path = DEFAULT_DATA_DIR / "processed"
    analysis_dir: Path = DEFAULT_DATA_DIR / "analysis"
    style_cache_dir: Path = DEFAULT_DATA_DIR / "style_cache"
    style_cache_novel_id: str = "longzu"
    corpus_source_dir: Path = DEFAULT_CORPUS_SOURCE_DIR
    allowed_external_corpus_roots: tuple[Path, ...] = ()
    continuation_project_dir: Path = DEFAULT_CONTINUATION_PROJECT_DIR
    writing_project_dir: Path = DEFAULT_WRITING_PROJECT_DIR

    max_chapter_length: int = 20000
    config_warnings: list[str] = Field(default_factory=list)


def _env_value(env: Mapping[str, Any], name: str) -> str:
    value = env.get(name, "")
    return str(value).strip().strip('"').strip("'") if value is not None else ""


def _get_text(env: Mapping[str, Any], name: str, default: str) -> str:
    return _env_value(env, name) or default


def _get_api_key(env: Mapping[str, Any]) -> str:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY"):
        value = _env_value(env, name)
        if value:
            return value
    return ""


def _get_base_url(env: Mapping[str, Any]) -> str:
    for name in ("ANTHROPIC_BASE_URL", "DEEPSEEK_BASE_URL"):
        value = _env_value(env, name)
        if value:
            return value
    return "https://api.deepseek.com/anthropic"


def _resolve_path(raw: str, warnings: list[str], name: str, default: Path) -> Path:
    if not raw:
        return default
    if "\x00" in raw:
        warnings.append(f"{name} contains an invalid null byte; using default path.")
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _get_path(
    env: Mapping[str, Any],
    name: str,
    default: Path,
    warnings: list[str],
) -> Path:
    return _resolve_path(_env_value(env, name), warnings, name, default)


def _get_path_list(
    env: Mapping[str, Any],
    name: str,
    warnings: list[str],
) -> tuple[Path, ...]:
    raw = _env_value(env, name)
    if not raw:
        return ()
    values: list[Path] = []
    for index, item in enumerate(raw.split(","), start=1):
        item = item.strip()
        if item:
            values.append(
                _resolve_path(item, warnings, f"{name}[{index}]", PROJECT_ROOT)
            )
    return tuple(dict.fromkeys(values))


def _get_int(
    env: Mapping[str, Any],
    name: str,
    default: int,
    warnings: list[str],
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = _env_value(env, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        warnings.append(f"{name} must be an integer; using {default}.")
        return default
    if not minimum <= value <= maximum:
        warnings.append(f"{name} must be between {minimum} and {maximum}; using {default}.")
        return default
    return value


def _get_frontend_origins(
    env: Mapping[str, Any],
    name: str,
    default: tuple[str, ...],
    warnings: list[str],
) -> tuple[str, ...]:
    raw = _env_value(env, name)
    if not raw:
        return default
    origins = tuple(
        item.rstrip("/")
        for item in (part.strip() for part in raw.split(","))
        if item
    )
    if not origins:
        warnings.append(f"{name} is empty after parsing; using default origins.")
        return default
    invalid = [
        item
        for item in origins
        if item != "*" and not item.startswith(("http://", "https://"))
    ]
    if invalid:
        warnings.append(
            f"{name} contains invalid origin values; using default origins."
        )
        return default
    return origins


def build_settings(env: Mapping[str, Any] | None = None) -> Settings:
    env = os.environ if env is None else env
    warnings: list[str] = []
    settings = Settings()

    settings.anthropic_api_key = _get_api_key(env)
    settings.anthropic_base_url = _get_base_url(env)
    settings.anthropic_model = _get_text(
        env,
        "ANTHROPIC_MODEL",
        settings.anthropic_model,
    )
    settings.anthropic_default_haiku_model = _get_text(
        env,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        settings.anthropic_default_haiku_model,
    )

    settings.host = _get_text(env, "HOST", DEFAULT_HOST)
    settings.port = _get_int(
        env,
        "PORT",
        DEFAULT_PORT,
        warnings,
        minimum=1,
        maximum=65535,
    )
    settings.frontend_origins = _get_frontend_origins(
        env,
        "FRONTEND_ORIGINS",
        DEFAULT_FRONTEND_ORIGINS,
        warnings,
    )

    settings.project_id = _get_text(env, "PROJECT_ID", DEFAULT_PROJECT_ID)
    settings.project_title = _get_text(env, "PROJECT_TITLE", DEFAULT_PROJECT_TITLE)

    settings.data_dir = _get_path(env, "DATA_DIR", DEFAULT_DATA_DIR, warnings)
    settings.projects_dir = _get_path(
        env,
        "PROJECTS_DIR",
        settings.data_dir / "projects",
        warnings,
    )
    settings.raw_dir = _get_path(env, "RAW_DIR", settings.data_dir / "raw", warnings)
    settings.processed_dir = _get_path(
        env,
        "PROCESSED_DIR",
        settings.data_dir / "processed",
        warnings,
    )
    settings.analysis_dir = _get_path(
        env,
        "ANALYSIS_DIR",
        settings.data_dir / "analysis",
        warnings,
    )
    settings.style_cache_dir = _get_path(
        env,
        "STYLE_CACHE_DIR",
        settings.data_dir / "style_cache",
        warnings,
    )
    settings.corpus_source_dir = _get_path(
        env,
        "CORPUS_SOURCE_DIR",
        settings.data_dir / "books" / "longzu" / "source_txt",
        warnings,
    )
    settings.allowed_external_corpus_roots = _get_path_list(
        env,
        "EXTERNAL_CORPUS_ROOTS",
        warnings,
    )
    settings.continuation_project_dir = _get_path(
        env,
        "CONTINUATION_PROJECT_DIR",
        settings.data_dir / "projects" / "longzu_continuation",
        warnings,
    )
    settings.writing_project_dir = _get_path(
        env,
        "WRITING_PROJECT_DIR",
        DEFAULT_WRITING_PROJECT_DIR,
        warnings,
    )
    settings.config_warnings = warnings
    return settings


settings = build_settings()
