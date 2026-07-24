from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import (
    AIChapterReviewResult,
    AnalysisDimension,
    BookPlan,
    BookPlanChapter,
    Chapter,
    CorpusStatus,
    DimensionResult,
    PlotBeatReview,
    TaskType,
    TempGenerationCreate,
)
from app.routers.analysis import _style_profiles
from app.routers.generation import _generation_results
from app.services.file_ops import safe_child
from app.services.project_context import use_project
from app.services.project_paths import get_project_paths
from app.services.project_profile import get_project_profile
from app.services.knowledge_base import KnowledgeBaseExtractor
from app.services.preprocessor import TextPreprocessor
from app.services.project_runtime import clear_project_runtime
from app.services.project_store import project_store
from app.services.task_manager import task_manager
from app.services.writing_project_store import writing_project_store


@pytest.fixture
def isolated_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_root = project_store.root
    original_task_storage_root = task_manager.storage_root
    legacy_data = tmp_path / "legacy-data"
    legacy_source = legacy_data / "books" / "legacy" / "source_txt"
    legacy_processed = legacy_data / "processed"
    legacy_analysis = legacy_data / "analysis"
    legacy_style = legacy_data / "style"
    legacy_planning = legacy_data / "legacy-planning"
    legacy_writing = tmp_path / "legacy-writing"

    monkeypatch.setattr(settings, "project_id", "legacytest")
    monkeypatch.setattr(settings, "project_title", "Legacy Test Project")
    monkeypatch.setattr(settings, "data_dir", legacy_data)
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    monkeypatch.setattr(settings, "corpus_source_dir", legacy_source)
    monkeypatch.setattr(settings, "processed_dir", legacy_processed)
    monkeypatch.setattr(settings, "analysis_dir", legacy_analysis)
    monkeypatch.setattr(settings, "style_cache_dir", legacy_style)
    monkeypatch.setattr(settings, "continuation_project_dir", legacy_planning)
    monkeypatch.setattr(settings, "writing_project_dir", legacy_writing)
    project_store.set_root(settings.projects_dir)
    task_manager.set_storage_root(tmp_path / "tasks")

    yield {
        "root": tmp_path,
        "legacy_data": legacy_data,
        "legacy_source": legacy_source,
        "legacy_processed": legacy_processed,
        "legacy_analysis": legacy_analysis,
        "legacy_style": legacy_style,
        "legacy_planning": legacy_planning,
        "legacy_writing": legacy_writing,
    }

    if project_store.root.exists():
        for manifest in project_store.root.glob("*/project.json"):
            clear_project_runtime(manifest.parent.name)
    task_manager.clear()
    task_manager.set_storage_root(original_task_storage_root)
    project_store.set_root(original_root)


def _create_project(client: TestClient, project_id: str, title: str) -> dict:
    response = client.post(
        "/api/projects",
        json={
            "project_id": project_id,
            "title": title,
            "project_type": "original",
            "corpus_config": {"mode": "managed", "source_paths": []},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _project_headers(project_id: str) -> dict[str, str]:
    return {"X-Project-ID": project_id}


def test_two_projects_isolate_corpus_tasks_and_official_chapters(
    isolated_projects,
) -> None:
    client = TestClient(app)
    project_a = _create_project(client, "project_a", "项目甲")
    project_b = _create_project(client, "project_b", "项目乙")

    upload_a = client.post(
        "/api/corpus/chapters/upload",
        headers=_project_headers(project_a["project_id"]),
        files={"file": ("a.txt", "甲项目章节内容".encode("utf-8"), "text/plain")},
    )
    upload_b = client.post(
        "/api/corpus/chapters/upload",
        headers=_project_headers(project_b["project_id"]),
        files={"file": ("b.txt", "乙项目独立章节".encode("utf-8"), "text/plain")},
    )
    assert upload_a.status_code == 200, upload_a.text
    assert upload_b.status_code == 200, upload_b.text

    for project_id, anchor_id in (
        ("project_a", upload_a.json()["chapter_id"]),
        ("project_b", upload_b.json()["chapter_id"]),
    ):
        headers = _project_headers(project_id)
        assert client.put(
            "/api/outline",
            headers=headers,
            json={"title": f"{project_id}-outline"},
        ).status_code == 200
        assert client.post(
            "/api/chapter-plans",
            headers=headers,
            json={
                "title": f"{project_id}-plan",
                "anchor_chapter_id": anchor_id,
                "target_words": 1200,
            },
        ).status_code == 200
        draft = client.post(
            "/api/drafts",
            headers=headers,
            json={
                "title": f"{project_id}-draft",
                "source_anchor_chapter_id": anchor_id,
            },
        )
        assert draft.status_code == 200, draft.text
        assert client.put(
            f"/api/drafts/{draft.json()['draft_id']}",
            headers=headers,
            json={
                "title": f"{project_id}-draft",
                "content": f"{project_id}-draft-content",
            },
        ).status_code == 200
        assert client.post(
            "/api/chapter-generation/save-temp",
            headers=headers,
            json={
                "chapter_title": f"{project_id}-temp",
                "content": f"{project_id}-temp-content",
            },
        ).status_code == 200
        with use_project(project_id):
            _style_profiles["profile"] = {"owner": project_id}
            _generation_results["generation"] = {"owner": project_id}

    chapters_a = client.get(
        "/api/corpus/chapters", headers=_project_headers("project_a")
    ).json()
    chapters_b = client.get(
        "/api/corpus/chapters", headers=_project_headers("project_b")
    ).json()
    assert [item["title"] for item in chapters_a] == ["a"]
    assert [item["title"] for item in chapters_b] == ["b"]
    assert client.get(
        f"/api/corpus/chapters/{upload_b.json()['chapter_id']}",
        headers=_project_headers("project_a"),
    ).status_code == 404

    official_a = client.post(
        "/api/chapter-generation/save-official",
        headers=_project_headers("project_a"),
        json={"title": "甲项目第一章", "content": "甲项目正式正文", "chapter_order": 1},
    )
    official_b = client.post(
        "/api/chapter-generation/save-official",
        headers=_project_headers("project_b"),
        json={"title": "乙项目第一章", "content": "乙项目正式正文", "chapter_order": 1},
    )
    assert official_a.status_code == 200, official_a.text
    assert official_b.status_code == 200, official_b.text
    assert [item["title"] for item in client.get(
        "/api/official-chapters", headers=_project_headers("project_a")
    ).json()] == ["甲项目第一章"]
    assert [item["title"] for item in client.get(
        "/api/official-chapters", headers=_project_headers("project_b")
    ).json()] == ["乙项目第一章"]

    for project_id in ("project_a", "project_b"):
        headers = _project_headers(project_id)
        assert client.get("/api/outline", headers=headers).json()["title"] == (
            f"{project_id}-outline"
        )
        assert [
            item["title"]
            for item in client.get("/api/chapter-plans", headers=headers).json()
        ] == [f"{project_id}-plan"]
        assert [
            item["title"]
            for item in client.get("/api/drafts", headers=headers).json()
        ] == [f"{project_id}-draft"]
        assert [
            item["chapter_title"]
            for item in client.get("/api/temp-generations", headers=headers).json()
        ] == [f"{project_id}-temp"]
        with use_project(project_id):
            assert _style_profiles["profile"]["owner"] == project_id
            assert _generation_results["generation"]["owner"] == project_id

    export_a = client.post(
        f"/api/official-chapters/{official_a.json()['chapter_id']}/export",
        headers=_project_headers("project_a"),
        json={"format": "txt"},
    )
    export_b = client.post(
        f"/api/official-chapters/{official_b.json()['chapter_id']}/export",
        headers=_project_headers("project_b"),
        json={"format": "txt"},
    )
    assert export_a.status_code == 200
    assert export_b.status_code == 200
    assert "甲项目正式正文".encode("utf-8") in export_a.content
    assert "乙项目正式正文".encode("utf-8") in export_b.content
    assert "乙项目正式正文".encode("utf-8") not in export_a.content

    with use_project("project_a"):
        task_a = task_manager.create(
            TaskType.GENERATION,
            target_id="chapter-a",
            user_visible_title="生成甲项目章节",
        )
    with use_project("project_b"):
        task_b = task_manager.create(
            TaskType.GENERATION,
            target_id="chapter-b",
            user_visible_title="生成乙项目章节",
        )

    tasks_a = client.get("/api/tasks", headers=_project_headers("project_a")).json()
    tasks_b = client.get("/api/tasks", headers=_project_headers("project_b")).json()
    assert [item["task_id"] for item in tasks_a] == [task_a.task_id]
    assert [item["task_id"] for item in tasks_b] == [task_b.task_id]
    assert client.get(
        f"/api/tasks/{task_b.task_id}", headers=_project_headers("project_a")
    ).status_code == 404
    assert client.post(
        f"/api/tasks/{task_b.task_id}/cancel",
        headers=_project_headers("project_a"),
    ).status_code == 404

    summary_a = client.get("/api/projects/project_a/summary").json()
    summary_b = client.get("/api/projects/project_b/summary").json()
    assert summary_a["corpus_chapter_count"] == 1
    assert summary_b["corpus_chapter_count"] == 1
    assert summary_a["official_chapter_count"] == 1
    assert summary_b["official_chapter_count"] == 1


def test_project_title_changes_without_changing_identity_or_path(
    isolated_projects,
) -> None:
    client = TestClient(app)
    project = _create_project(client, "stable_project", "原项目名称")
    path_before = project_store.project_path(project["project_id"])

    response = client.put(
        "/api/projects/stable_project",
        json={"title": "修改后的中文项目名"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == "stable_project"
    assert project_store.project_path("stable_project") == path_before
    assert path_before.is_dir()


def test_invalid_project_ids_and_path_traversal_are_rejected(
    isolated_projects,
) -> None:
    client = TestClient(app)
    response = client.post(
        "/api/projects",
        json={"project_id": "../escape", "title": "非法项目"},
    )
    assert response.status_code == 422
    with pytest.raises(ValueError):
        project_store.project_path("../escape")
    with pytest.raises(ValueError):
        safe_child(project_store.root, "..", "escape")
    assert client.get(
        "/api/health", headers={"X-Project-ID": "../escape"}
    ).status_code == 400
    assert client.get(
        "/api/health", headers={"X-Project-ID": "missing_project"}
    ).status_code == 404
    inline_secret = client.post(
        "/api/projects",
        json={
            "project_id": "secret_project",
            "title": "密钥校验",
            "model_config_ref": {"api_key": "must-not-be-stored"},
        },
    )
    assert inline_secret.status_code == 422
    assert "must-not-be-stored" not in inline_secret.text


def test_external_corpus_requires_an_explicit_allowed_root(
    isolated_projects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    external = isolated_projects["root"] / "external-corpus"
    external.mkdir()

    rejected = client.post(
        "/api/projects",
        json={
            "project_id": "external_rejected",
            "title": "未授权外部语料",
            "corpus_config": {
                "mode": "external_readonly",
                "source_paths": [str(external)],
            },
        },
    )
    assert rejected.status_code == 400
    assert "EXTERNAL_CORPUS_ROOTS" in rejected.json()["message"]

    monkeypatch.setattr(settings, "allowed_external_corpus_roots", (external,))
    accepted = client.post(
        "/api/projects",
        json={
            "project_id": "external_allowed",
            "title": "已授权外部语料",
            "corpus_config": {
                "mode": "external_readonly",
                "source_paths": [str(external)],
            },
        },
    )
    assert accepted.status_code == 201, accepted.text
    with use_project("external_allowed"):
        assert get_project_paths().source == external.resolve()


def test_upload_limits_error_envelope_and_soft_delete(
    isolated_projects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    project_id = "upload_security"
    _create_project(client, project_id, "上传安全测试")
    headers = _project_headers(project_id)
    monkeypatch.setattr(settings, "upload_max_bytes", 16)

    invalid_type = client.post(
        "/api/corpus/chapters/upload",
        headers=headers,
        files={"file": ("notes.md", b"plain text", "text/markdown")},
    )
    assert invalid_type.status_code == 415
    assert invalid_type.json()["error_code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert invalid_type.json()["request_id"]
    assert invalid_type.headers["X-Request-ID"] == invalid_type.json()["request_id"]

    oversized = client.post(
        "/api/corpus/chapters/upload",
        headers=headers,
        files={"file": ("chapter.txt", b"x" * 17, "text/plain")},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error_code"] == "UPLOAD_TOO_LARGE"

    uploaded = client.post(
        "/api/corpus/chapters/upload",
        headers=headers,
        files={"file": ("chapter.txt", b"original text", "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    chapter_id = uploaded.json()["chapter_id"]
    deleted = client.delete(f"/api/corpus/chapters/{chapter_id}", headers=headers)
    assert deleted.status_code == 200
    trash = project_store.layout(project_id).corpus / "trash" / "processed"
    assert list(trash.glob(f"{chapter_id}.txt.*"))

    validation = client.post(
        "/api/projects",
        json={"project_id": "../escape", "title": "非法项目"},
    )
    assert validation.status_code == 422
    assert set(validation.json()) == {
        "error_code",
        "message",
        "details",
        "request_id",
        "retryable",
    }
    assert "input" not in json.dumps(validation.json(), ensure_ascii=False)


def test_large_project_uses_paginated_metadata_and_history_summaries(
    isolated_projects,
) -> None:
    client = TestClient(app)
    project_id = "large_project"
    _create_project(client, project_id, "大项目分页测试")
    headers = _project_headers(project_id)

    from app.routers.corpus import _corpus_store, _loaded_projects

    with use_project(project_id):
        for index in range(350):
            chapter_id = f"chapter-{index:04d}"
            _corpus_store[chapter_id] = Chapter(
                chapter_id=chapter_id,
                series_order=1,
                volume_key="volume-1",
                volume_display_name="第一卷",
                chapter_order=index + 1,
                title=f"原创章节 {index + 1}",
                word_count=8000,
                content="原创正文",
                status=CorpusStatus.PROCESSED,
            )
        _loaded_projects.add(project_id)
        for index in range(20):
            writing_project_store.create_temp_generation(
                TempGenerationCreate(
                    chapter_order=index + 1,
                    chapter_title=f"候选章 {index + 1}",
                    content="仅用于性能测试的原创文本。" * 800,
                )
            )

    page = client.get(
        "/api/corpus/chapters/page?offset=100&limit=100",
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["total"] == 350
    assert len(page.json()["items"]) == 100
    assert page.json()["has_more"] is True

    history = client.get(
        "/api/temp-generations/page?offset=0&limit=10",
        headers=headers,
    )
    assert history.status_code == 200
    assert history.json()["total"] == 20
    assert len(history.json()["items"]) == 10
    assert all("content" not in item for item in history.json()["items"])
    assert all("generation_request" not in item for item in history.json()["items"])


def test_managed_project_uses_generic_runtime_profile(isolated_projects) -> None:
    client = TestClient(app)
    _create_project(client, "generic_project", "原创中文项目")

    legacy_prompt = (
        "你是江南，中国著名幻想小说作家，《龙族》系列的作者。\n"
        "请续写《龙族》。"
    )
    with use_project("generic_project"):
        profile = get_project_profile()
        adapted = profile.adapt_legacy_prompt(legacy_prompt)
        chapters = TextPreprocessor().process(
            "第一章 开始\n这是原创项目正文。",
            "01_火之晨曦",
        )
        fallback_characters = KnowledgeBaseExtractor()._fallback_characters(
            "路明非路明非路明非"
        )
    assert profile.legacy is False
    assert "原创中文项目" in adapted
    assert "江南" not in adapted
    assert "龙族" not in adapted
    assert chapters[0].volume_display_name == "01_火之晨曦"
    assert fallback_characters == []

    with use_project(settings.project_id):
        assert get_project_profile().adapt_legacy_prompt(legacy_prompt) == legacy_prompt
        legacy_chapters = TextPreprocessor().process(
            "第一章 开始\n这是旧项目正文。",
            "01_火之晨曦",
        )
    assert legacy_chapters[0].volume_display_name == "龙族 I：火之晨曦"


def test_empty_data_root_can_start_before_first_project_is_created(
    isolated_projects,
) -> None:
    from app.routers.corpus import _scan_processed

    isolated_projects["legacy_source"].mkdir(parents=True)
    isolated_projects["legacy_processed"].mkdir(parents=True)
    isolated_projects["legacy_analysis"].mkdir(parents=True)
    isolated_projects["legacy_style"].mkdir(parents=True)
    isolated_projects["legacy_planning"].mkdir(parents=True)
    isolated_projects["legacy_writing"].mkdir(parents=True)
    isolated_projects["legacy_planning"].joinpath("chapter_plans.json").write_text(
        "[]", encoding="utf-8"
    )
    isolated_projects["legacy_planning"].joinpath("outline.json").write_text(
        json.dumps(
            {
                "title": "本地续写项目",
                "premise": "",
                "main_conflict": "",
                "tone": "",
                "ending_direction": "",
                "continuity_notes": [],
                "foreshadowing": [],
                "character_arcs": [],
                "prohibitions": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    isolated_projects["legacy_planning"].joinpath("manifest.json").write_text(
        '{"chapters": []}', encoding="utf-8"
    )
    isolated_projects["legacy_writing"].joinpath("manifest.json").write_text(
        "{}", encoding="utf-8"
    )
    with use_project(settings.project_id):
        _scan_processed()
    assert project_store.list_projects() == []


def test_soft_delete_is_confirmed_and_does_not_affect_other_project(
    isolated_projects,
) -> None:
    client = TestClient(app)
    _create_project(client, "delete_me", "待删除项目")
    _create_project(client, "keep_me", "保留项目")
    client.post(
        "/api/chapter-generation/save-official",
        headers=_project_headers("keep_me"),
        json={"title": "保留章节", "content": "必须保留", "chapter_order": 1},
    )
    deleted_task = task_manager.create(
        TaskType.GENERATION,
        project_id="delete_me",
    )
    kept_task = task_manager.create(
        TaskType.GENERATION,
        project_id="keep_me",
    )

    rejected = client.delete(
        "/api/projects/delete_me", params={"confirm_project_id": "wrong"}
    )
    assert rejected.status_code == 409
    deleted = client.delete(
        "/api/projects/delete_me", params={"confirm_project_id": "delete_me"}
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["recoverable"] is True
    assert Path(deleted.json()["trash_path"]).is_dir()
    assert client.get("/api/projects/delete_me").status_code == 404
    assert client.get("/api/projects/keep_me").status_code == 200
    assert task_manager.get(deleted_task.task_id, project_id="delete_me") is None
    assert task_manager.get(kept_task.task_id, project_id="keep_me") is not None
    assert list((task_manager.storage_root / ".trash").glob("delete_me.*"))
    chapters = client.get(
        "/api/official-chapters", headers=_project_headers("keep_me")
    ).json()
    assert [item["title"] for item in chapters] == ["保留章节"]


def test_legacy_project_preview_and_migration_preserve_statistics(
    isolated_projects,
) -> None:
    env = isolated_projects
    source = env["legacy_source"]
    processed = env["legacy_processed"]
    writing = env["legacy_writing"]
    planning = env["legacy_planning"]
    source.mkdir(parents=True)
    processed.mkdir(parents=True)
    writing.joinpath("official_chapters").mkdir(parents=True)
    writing.joinpath("temp_generations").mkdir(parents=True)
    planning.mkdir(parents=True)

    source_file = source / "original.txt"
    source_file.write_text("只读测试语料", encoding="utf-8")
    source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    source_timestamp = source_file.stat().st_mtime_ns
    processed.joinpath("chapter-001.txt").write_text("处理后章节", encoding="utf-8")
    env["legacy_data"].joinpath("chapters_meta.json").write_text(
        json.dumps(
            {
                "chapter-001": {
                    "chapter_id": "chapter-001",
                    "title": "测试章节",
                    "word_count": 1234,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    writing.joinpath("official_chapters", "chapter_001.json").write_text(
        "{}", encoding="utf-8"
    )
    writing.joinpath("temp_generations", "temp_000001.json").write_text(
        "{}", encoding="utf-8"
    )
    planning.joinpath("chapter_plans.json").write_text("[]", encoding="utf-8")

    client = TestClient(app)
    legacy = client.get("/api/projects/legacytest")
    assert legacy.status_code == 200
    assert legacy.json()["storage_mode"] == "legacy"

    preview = client.get("/api/projects/legacytest/migration-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["chapter_count"] == 1
    assert preview.json()["total_words"] == 1234
    assert preview.json()["source_corpus_will_be_copied"] is False

    migrated = client.post(
        "/api/projects/legacytest/migrate",
        json={
            "title": "迁移测试项目",
            "target_project_id": "migrated_project",
            "confirm_source_project_id": "legacytest",
            "corpus_mode": "reference",
        },
    )
    assert migrated.status_code == 201, migrated.text
    result = migrated.json()
    assert result["chapter_count_before"] == result["chapter_count_after"] == 1
    assert result["total_words_before"] == result["total_words_after"] == 1234
    assert Path(result["backup_path"]).is_file()
    assert source_file.is_file()
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == source_hash
    assert source_file.stat().st_mtime_ns == source_timestamp

    migrated_summary = client.get(
        "/api/projects/migrated_project/summary"
    ).json()
    assert migrated_summary["corpus_chapter_count"] == 1
    assert migrated_summary["corpus_word_count"] == 1234
    assert client.get("/api/projects/legacytest").status_code == 200


def test_failed_legacy_migration_is_removed_from_active_projects(
    isolated_projects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = isolated_projects
    env["legacy_source"].mkdir(parents=True)
    env["legacy_processed"].mkdir(parents=True)
    env["legacy_writing"].mkdir(parents=True)
    env["legacy_planning"].mkdir(parents=True)
    source_file = env["legacy_source"] / "original.txt"
    source_file.write_text("迁移失败回滚测试", encoding="utf-8")
    source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    env["legacy_data"].joinpath("chapters_meta.json").write_text(
        json.dumps(
            {"chapter-001": {"chapter_id": "chapter-001", "word_count": 10}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    original_stats = project_store._chapter_stats

    def mismatched_target_stats(path: Path) -> tuple[int, int]:
        if "failed_target" in path.parts:
            return 2, 999
        return original_stats(path)

    monkeypatch.setattr(project_store, "_chapter_stats", mismatched_target_stats)
    client = TestClient(app)
    response = client.post(
        "/api/projects/legacytest/migrate",
        json={
            "title": "失败迁移测试",
            "target_project_id": "failed_target",
            "confirm_source_project_id": "legacytest",
            "corpus_mode": "reference",
        },
    )

    assert response.status_code == 409, response.text
    assert client.get("/api/projects/failed_target").status_code == 404
    failed_manifests = list(
        settings.projects_dir.glob(".failed_migrations/failed_target-*/project.json")
    )
    assert len(failed_manifests) == 1
    failed_project = json.loads(failed_manifests[0].read_text(encoding="utf-8"))
    assert failed_project["migration_state"] == "failed"
    assert list(settings.projects_dir.glob(".migration_backups/*.zip"))
    assert client.get("/api/projects/legacytest").status_code == 200
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == source_hash


def test_phase4_original_creation_flow_uses_only_temporary_data_and_mock_models(
    isolated_projects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    project_id = "phase4_original"
    project = _create_project(client, project_id, "原创闭环验收项目")
    headers = _project_headers(project_id)
    layout = project_store.layout(project_id)
    assert str(layout.root).startswith(str(isolated_projects["root"]))

    layout.corpus_source.mkdir(parents=True, exist_ok=True)
    original_source = layout.corpus_source / "original_fixture.txt"
    original_source.write_text(
        "第一章 灯塔来信\n"
        "清晨的港口没有船鸣。林澈收到一封来自废弃灯塔的手写信，"
        "信中只画着潮汐刻度和一枚从未见过的印章。她决定在涨潮前查明来信者。\n"
        "第二章 潮线之下\n"
        "林澈沿防波堤找到被海水遮住的旧门，门后留下新的坐标。",
        encoding="utf-8",
    )
    scan = client.post("/api/corpus/scan-local", headers=headers)
    assert scan.status_code == 200, scan.text
    chapters = client.get("/api/corpus/chapters", headers=headers).json()
    assert chapters
    anchor_id = chapters[-1]["chapter_id"]

    analysis_result = [
        DimensionResult(
            dimension=AnalysisDimension.NARRATIVE_PERSPECTIVE,
            summary="第三人称限知视角，叙事克制。",
            details={"source": "mock"},
        )
    ]
    with patch(
        "app.services.style_analyzer.analyze_chapter",
        new=AsyncMock(return_value=analysis_result),
    ):
        analysis = client.post(f"/api/analysis/analyze/{anchor_id}", headers=headers)
    assert analysis.status_code == 200, analysis.text
    analysis_task = client.get(
        f"/api/analysis/tasks/{analysis.json()['task_id']}", headers=headers
    ).json()
    assert analysis_task["status"] == "completed"

    monkeypatch.setattr(settings, "anthropic_api_key", "mock-key-for-tests-only")
    skeletons = [
        BookPlanChapter(
            order=index,
            title=f"潮汐计划 {index}",
            chapter_summary=f"林澈推进第 {index} 阶段调查。",
            chapter_goal="推进灯塔来信的调查",
            target_words=5000,
        )
        for index in range(1, 4)
    ]
    conceived = BookPlan(
        project_id=project_id,
        source_anchor_chapter_id=anchor_id,
        target_scale="short",
        target_chapter_count=3,
        automation_level="chapter_by_chapter",
        title="潮线之外",
        premise="林澈追查灯塔来信并面对记忆与责任的选择。",
        core_theme="记忆与责任",
        focus_characters=["林澈"],
        main_conflict="调查真相会危及港口居民",
        tone="克制、清晰",
        ending_direction="林澈公开证据并承担选择的后果",
        chapters=skeletons,
        chapter_plans_complete=False,
        model_name="mock-model",
    )
    with patch(
        "app.services.book_planner.conceive_book_plan",
        new=AsyncMock(return_value=conceived),
    ):
        planning = client.post(
            "/api/book-plan/generate",
            headers=headers,
            json={
                "source_anchor_chapter_id": anchor_id,
                "rough_direction": "",
                "target_scale": "short",
                "target_chapter_count": 3,
                "automation_level": "chapter_by_chapter",
                "auto_create_chapter_plans": False,
            },
        )
    assert planning.status_code == 200, planning.text
    planning_task = client.get(
        f"/api/tasks/{planning.json()['task_id']}", headers=headers
    ).json()
    assert planning_task["status"] == "success"
    assert planning_task["result"]["book_plan"]["accepted"] is False

    blocked_completion = client.post(
        "/api/book-plan/complete-chapter-plans", headers=headers
    )
    assert blocked_completion.status_code == 409
    accepted_response = client.post("/api/book-plan/accept", headers=headers)
    assert accepted_response.status_code == 200, accepted_response.text
    accepted_plan = BookPlan.model_validate(accepted_response.json())

    detailed_chapters = [
        BookPlanChapter(
            order=index,
            title=f"潮汐计划 {index}",
            chapter_summary=f"林澈根据第 {index} 组坐标推进调查并获得证据。",
            chapter_goal="推进灯塔来信调查并明确本章选择的代价",
            opening_state="承接上一章留下的潮汐坐标和未完成行动",
            ending_state="林澈取得阶段性证据，同时发现新的风险入口",
            previous_bridge="延续上一章结尾出现的坐标和行动方向",
            next_bridge="将新证据中的下一处坐标交给后续章节追查",
            plot_beats=["核对坐标", "遭遇阻力", "取得证据"],
            chapter_function=["推进主线"],
            characters=["林澈"],
            conflict="林澈必须在保护居民和公开证据之间作出选择",
            emotional_tone="克制而紧张",
            word_count_reason="调查、冲突和选择需要完整展开并留下章节钩子",
            ending_hook="证据中出现下一处潮汐坐标",
            target_words=5000,
        )
        for index in range(1, 4)
    ]
    completed_plan = accepted_plan.model_copy(
        update={"chapters": detailed_chapters, "chapter_plans_complete": True}
    )
    with patch(
        "app.services.chapter_planner.complete_book_plan_chapters",
        new=AsyncMock(return_value=(completed_plan, [])),
    ):
        completion = client.post(
            "/api/book-plan/complete-chapter-plans", headers=headers
        )
    assert completion.status_code == 200, completion.text
    completion_task = client.get(
        f"/api/tasks/{completion.json()['task_id']}", headers=headers
    ).json()
    assert completion_task["status"] == "success"
    plans = client.get("/api/chapter-plans", headers=headers).json()
    assert len(plans) == 3
    assert all(item["status"] == "planned" for item in plans)
    first_plan, second_plan = plans[0], plans[1]

    base = "林澈沿潮线核对坐标，避开巡逻后取得证据，并发现下一处入口。"
    generated_text = (base * (8085 // len(base) + 1))[:8085] + "。"
    assert len(generated_text) == 8086
    with patch(
        "app.services.generator.generate_chapter",
        new=AsyncMock(return_value=(generated_text, "mock-system")),
    ):
        generation = client.post(
            "/api/chapter-generation/full-chapter/start",
            headers=headers,
            json={
                "start_chapter_id": anchor_id,
                "source_anchor_chapter_id": anchor_id,
                "plot_direction": "",
                "target_word_count": 5000,
                "mode": "chapter",
                "draft_id": first_plan["draft_id"],
                "plan_id": first_plan["plan_id"],
                "append_to_draft": False,
                "reference_chapter_ids": [],
                "pov_character": "林澈",
                "additional_instructions": "",
                "generation_kind": "full_chapter",
            },
        )
    assert generation.status_code == 200, generation.text
    generation_task = client.get(
        f"/api/tasks/{generation.json()['task_id']}", headers=headers
    ).json()
    assert generation_task["status"] == "success"
    generated_result = generation_task["result"]["generation_result"]
    assert generated_result["content"] == generated_text
    assert generation_task["result"]["temp_generation"]["saved_official"] is False
    assert client.get(
        f"/api/chapter-plans/{first_plan['plan_id']}", headers=headers
    ).json()["status"] == "draft_review"

    revised_text = "林澈重新核对潮汐刻度。" + generated_text[12:]
    with patch(
        "app.services.generator.iterate_chapter",
        new=AsyncMock(return_value=(revised_text, "mock-system")),
    ):
        revision = client.post(
            "/api/tasks/revision/start",
            headers=headers,
            json={
                "generation_id": generated_result["id"],
                "feedback": "只修改开头动作，使目标更清楚",
                "target_section": "开头",
                "current_text": generated_text,
                "revision_mode": "local_edit",
            },
        )
    assert revision.status_code == 200, revision.text
    revision_task = client.get(
        f"/api/tasks/{revision.json()['task_id']}", headers=headers
    ).json()
    assert revision_task["status"] in {"success", "partial_success"}
    assert revision_task["result"]["generation_result"]["content"] == revised_text
    assert revision_task["result"]["original_text"] == generated_text
    assert generated_text != revised_text

    report = AIChapterReviewResult(
        plan_id=first_plan["plan_id"],
        generation_id=revision_task["result"]["generation_result"]["id"],
        overall_pass=True,
        score=88,
        summary_alignment="正文覆盖调查和取得证据。",
        summary_aligned=True,
        plot_beats_coverage=[
            PlotBeatReview(beat=beat, covered=True, evidence="正文已覆盖")
            for beat in detailed_chapters[0].plot_beats
        ],
        ending_state_alignment="结尾取得阶段性证据。",
        ending_state_aligned=True,
        continuity_with_previous="承接潮汐坐标。",
        continuity_previous_pass=True,
        continuity_with_next="留下下一处入口。",
        continuity_next_pass=True,
        character_consistency="人物行为一致。",
        character_consistent=True,
        style_consistency="叙事风格一致。",
        style_consistent=True,
        need_repair=False,
        model_name="mock-model",
    )
    with patch(
        "app.services.chapter_reviewer.ChapterReviewService.review",
        new=AsyncMock(return_value=report),
    ):
        review = client.post(
            "/api/chapter-generation/ai-review/start",
            headers=headers,
            json={
                "generation_id": report.generation_id,
                "plan_id": first_plan["plan_id"],
                "content": revised_text,
            },
        )
    assert review.status_code == 200, review.text
    review_task = client.get(
        f"/api/tasks/{review.json()['task_id']}", headers=headers
    ).json()
    assert review_task["status"] == "success"
    assert client.get(
        f"/api/chapter-plans/{first_plan['plan_id']}", headers=headers
    ).json()["status"] == "quality_checked"

    check = client.post(
        "/api/chapter-generation/check-completeness",
        headers=headers,
        json={"plan_id": first_plan["plan_id"], "content": revised_text},
    )
    assert check.status_code == 200, check.text
    check_result = check.json()
    assert check_result["can_save_official"] is True
    assert check_result["blocking_errors"] == []
    assert any(
        item["code"] == "chapter_above_recommended"
        for item in check_result["warnings"]
    )
    saved = client.post(
        "/api/chapter-generation/save-official",
        headers=headers,
        json={
            "title": first_plan["title"],
            "content": revised_text,
            "chapter_order": first_plan["order"],
            "source_generation_id": report.generation_id,
            "source_temp_id": revision_task["result"]["temp_generation"]["temp_id"],
            "source_plan_id": first_plan["plan_id"],
            "completeness_check": check_result,
            "chapter_plan_snapshot": first_plan,
        },
    )
    assert saved.status_code == 200, saved.text
    official = saved.json()
    assert official["saved_with_warnings"] is True
    assert client.get(
        f"/api/chapter-plans/{first_plan['plan_id']}", headers=headers
    ).json()["status"] == "official"
    assert client.get(
        f"/api/chapter-plans/{second_plan['plan_id']}", headers=headers
    ).json()["status"] == "planned"

    exported = client.post(
        f"/api/official-chapters/{official['chapter_id']}/export",
        headers=headers,
        json={"format": "txt"},
    )
    assert exported.status_code == 200, exported.text
    assert revised_text.encode("utf-8") in exported.content
    assert list((layout.writing / "exports").glob("*.txt"))
    summary = client.get(f"/api/projects/{project_id}/summary").json()
    assert summary["official_chapter_count"] == 1
    assert summary["current_chapter_order"] == second_plan["order"]
    assert summary["recommended_step"] == "generate"
    assert summary["recent_official_chapters"][0]["chapter_id"] == official["chapter_id"]
    assert project_store.root == isolated_projects["root"] / "projects"

    clear_project_runtime(project_id)
    reloaded_official = client.get(
        f"/api/official-chapters/{official['chapter_id']}",
        headers=headers,
    )
    assert reloaded_official.status_code == 200, reloaded_official.text
    assert reloaded_official.json()["content"] == revised_text
    restored_tasks = client.get("/api/tasks?limit=200", headers=headers).json()
    restored_ids = {item["task_id"] for item in restored_tasks}
    assert planning.json()["task_id"] in restored_ids
    assert generation.json()["task_id"] in restored_ids
    assert review.json()["task_id"] in restored_ids
