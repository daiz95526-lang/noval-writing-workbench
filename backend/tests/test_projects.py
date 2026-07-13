from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import TaskType
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


@pytest.fixture
def isolated_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_root = project_store.root
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
    assert "EXTERNAL_CORPUS_ROOTS" in rejected.json()["detail"]

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
