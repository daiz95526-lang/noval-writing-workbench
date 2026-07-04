from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import (  # noqa: E402
    DEFAULT_CONTINUATION_PROJECT_DIR,
    DEFAULT_CORPUS_SOURCE_DIR,
    DEFAULT_DATA_DIR,
    DEFAULT_FRONTEND_ORIGINS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_TITLE,
    DEFAULT_WRITING_PROJECT_DIR,
    PROJECT_ROOT,
    build_settings,
)


def test_default_paths_and_project_identity_remain_compatible() -> None:
    settings = build_settings({})

    assert settings.host == DEFAULT_HOST
    assert settings.port == DEFAULT_PORT
    assert settings.frontend_origins == DEFAULT_FRONTEND_ORIGINS
    assert settings.project_id == DEFAULT_PROJECT_ID == "longzu6"
    assert settings.project_title == DEFAULT_PROJECT_TITLE
    assert settings.data_dir == DEFAULT_DATA_DIR
    assert settings.corpus_source_dir == DEFAULT_CORPUS_SOURCE_DIR
    assert settings.continuation_project_dir == DEFAULT_CONTINUATION_PROJECT_DIR
    assert settings.writing_project_dir == DEFAULT_WRITING_PROJECT_DIR


def test_env_overrides_paths_and_project_metadata() -> None:
    settings = build_settings(
        {
            "HOST": "0.0.0.0",
            "PORT": "8020",
            "FRONTEND_ORIGINS": "http://localhost:3000, http://127.0.0.1:5173/",
            "PROJECT_ID": "custom_project",
            "PROJECT_TITLE": "Custom Project",
            "DATA_DIR": "./local-data",
            "CORPUS_SOURCE_DIR": "./local-corpus",
            "CONTINUATION_PROJECT_DIR": "./local-project",
            "WRITING_PROJECT_DIR": "./local-writing",
        }
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 8020
    assert settings.frontend_origins == (
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    )
    assert settings.project_id == "custom_project"
    assert settings.project_title == "Custom Project"
    assert settings.data_dir == (PROJECT_ROOT / "local-data").resolve()
    assert settings.corpus_source_dir == (PROJECT_ROOT / "local-corpus").resolve()
    assert settings.continuation_project_dir == (
        PROJECT_ROOT / "local-project"
    ).resolve()
    assert settings.writing_project_dir == (PROJECT_ROOT / "local-writing").resolve()


def test_invalid_port_and_origins_fall_back_with_warnings() -> None:
    settings = build_settings(
        {
            "PORT": "not-a-port",
            "FRONTEND_ORIGINS": "localhost:5173",
            "DATA_DIR": "bad\x00path",
        }
    )

    assert settings.port == DEFAULT_PORT
    assert settings.frontend_origins == DEFAULT_FRONTEND_ORIGINS
    assert settings.data_dir == DEFAULT_DATA_DIR
    assert any("PORT" in item for item in settings.config_warnings)
    assert any("FRONTEND_ORIGINS" in item for item in settings.config_warnings)
    assert any("DATA_DIR" in item for item in settings.config_warnings)
