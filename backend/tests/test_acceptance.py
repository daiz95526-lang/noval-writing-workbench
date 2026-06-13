from __future__ import annotations

import sys
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import (
    AIChapterReviewResult,
    AnalysisDimension,
    BookPlan,
    BookPlanChapter,
    BookPlanGenerateRequest,
    ChapterStyleCacheEntry,
    ChapterStyleJson,
    ChapterPlan,
    ChapterPlanInput,
    CharacterProfile,
    DimensionResult,
    GenerationRequest,
    GlobalStyleKnowledge,
    KnowledgeBase,
    PlotBeatReview,
    Theme,
    TaskType,
    WorldSetting,
)
from app.routers import generation as generation_router
from app.services.generator import ContinuationGenerator, GenerationServiceError
from app.services.generator import _apply_revision_edits, _revision_diagnostics
from app.services.chapter_planner import (
    ChapterPlanCompleter,
    book_plan_chapters_complete,
    chapter_plan_is_complete,
)
from app.services.chapter_quality import (
    check_chapter_completeness,
    ensure_complete_ending,
    truncate_to_complete_sentence,
)
from app.services.chapter_reviewer import parse_quality_check_response
from app.services.draft_store import DraftStore
from app.services.draft_store import draft_store
from app.services.planning_store import planning_store
from app.services.task_manager import task_manager
from app.services.writing_project_store import writing_project_store


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._original_style_cache_dir = settings.style_cache_dir
        cls._style_cache_temp = tempfile.TemporaryDirectory()
        settings.style_cache_dir = Path(cls._style_cache_temp.name)
        cls._original_project_root = draft_store.root
        cls._original_planning_root = planning_store.root
        cls._original_writing_root = writing_project_store.root
        cls._project_temp = tempfile.TemporaryDirectory()
        project_root = Path(cls._project_temp.name) / "longzu_continuation"
        draft_store.set_root(project_root)
        planning_store.set_root(project_root)
        writing_project_store.set_root(
            Path(cls._project_temp.name) / "writing_projects" / "longzu6"
        )
        cls.client = TestClient(app)
        response = cls.client.post("/api/corpus/scan-local")
        assert response.status_code == 200, response.text

    @classmethod
    def tearDownClass(cls) -> None:
        settings.style_cache_dir = cls._original_style_cache_dir
        cls._style_cache_temp.cleanup()
        draft_store.set_root(cls._original_project_root)
        planning_store.set_root(cls._original_planning_root)
        writing_project_store.set_root(cls._original_writing_root)
        cls._project_temp.cleanup()

    def test_config_status_is_safe_and_configured(self) -> None:
        response = self.client.get("/api/system/config-status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["has_api_key"])
        self.assertTrue(data["base_url_configured"])
        self.assertTrue(data["env_loaded"])
        self.assertNotIn("base_url", data)
        self.assertNotIn("api_key", data)

    def test_stats_and_chapter_contract(self) -> None:
        stats = self.client.get("/api/corpus/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["total_volumes"], 8)
        self.assertGreaterEqual(stats.json()["total_chapters"], 332)

        response = self.client.get("/api/corpus/chapters")
        self.assertEqual(response.status_code, 200)
        chapters = response.json()
        self.assertEqual(len(chapters), stats.json()["total_chapters"])
        self.assertEqual(
            len({chapter["chapter_id"] for chapter in chapters}),
            len(chapters),
        )
        required = {
            "chapter_id",
            "series_order",
            "sub_order",
            "volume_key",
            "volume_display_name",
            "chapter_order",
            "title",
            "word_count",
            "dialogue_ratio",
            "source_file",
            "content_hash",
        }
        self.assertTrue(required.issubset(chapters[0]))
        self.assertNotIn("id", chapters[0])
        self.assertNotIn("chapter_index", chapters[0])

    def test_generation_success_and_failure_are_not_fake(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0][
            "chapter_id"
        ]
        generation_router._knowledge_base = KnowledgeBase(
            themes=[
                Theme(
                    name="测试主题",
                    description="用于验收生成接口",
                )
            ]
        )
        payload = {
            "start_chapter_id": chapter_id,
            "plot_direction": "继续当前冲突",
            "target_word_count": 1000,
            "pov_character": "",
            "additional_instructions": "",
        }

        with patch(
            "app.services.generator.generate_chapter",
            new=AsyncMock(return_value=("非空测试正文", "system")),
        ):
            response = self.client.post("/api/generation/generate", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "非空测试正文")
        self.assertTrue(self.client.get("/api/generation/results").json())

        with patch(
            "app.services.generator.generate_chapter",
            new=AsyncMock(
                side_effect=GenerationServiceError("模型网络错误 (ConnectError)")
            ),
        ):
            response = self.client.post("/api/generation/generate", json=payload)
        self.assertEqual(response.status_code, 502)
        self.assertIn("ConnectError", response.json()["detail"])

    def test_volumes_three_four_five_have_readable_content(self) -> None:
        chapters = self.client.get("/api/corpus/chapters").json()
        for series_order in (3, 4, 5):
            chapter = next(
                item for item in chapters if item["series_order"] == series_order
            )
            response = self.client.get(
                f"/api/corpus/chapters/{chapter['chapter_id']}"
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["content"].strip())

    def test_style_and_knowledge_base_fallbacks_are_non_empty(self) -> None:
        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = ""
        try:
            chapter_id = self.client.get("/api/corpus/chapters").json()[0][
                "chapter_id"
            ]
            task = self.client.post(f"/api/analysis/analyze/{chapter_id}")
            self.assertEqual(task.status_code, 200)
            task_data = self.client.get(
                f"/api/analysis/tasks/{task.json()['task_id']}"
            ).json()
            self.assertEqual(task_data["status"], "completed")
            profile = self.client.get(
                f"/api/analysis/profiles/{task_data['message']}"
            ).json()
            self.assertTrue(profile["dimensions"])
            self.assertTrue(all(item["summary"] for item in profile["dimensions"]))

            kb_response = self.client.post("/api/generation/knowledge-base/build")
            self.assertEqual(kb_response.status_code, 200)
            kb = kb_response.json()
            self.assertTrue(kb["characters"])
            self.assertTrue(kb["world_settings"])
            self.assertTrue(kb["plot_nodes"])
            self.assertTrue(kb["themes"])

            generation = self.client.post(
                "/api/generation/generate",
                json={
                    "start_chapter_id": chapter_id,
                    "plot_direction": "继续当前冲突",
                    "target_word_count": 1000,
                    "pov_character": "",
                    "additional_instructions": "",
                },
            )
            self.assertEqual(generation.status_code, 400)
            self.assertIn("API Key", generation.json()["detail"])
        finally:
            settings.anthropic_api_key = original_key

    def test_scan_is_idempotent(self) -> None:
        before = self.client.get("/api/corpus/stats").json()["total_chapters"]
        response = self.client.post("/api/corpus/scan-local")
        self.assertEqual(response.status_code, 200)
        after = self.client.get("/api/corpus/stats").json()["total_chapters"]
        self.assertEqual(before, after)
        self.assertEqual(response.json()["new_chapters"], 0)

    def test_long_task_style_and_knowledge_endpoints(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = ""
        try:
            response = self.client.post(
                "/api/tasks/style-analysis/start",
                json={"chapter_id": chapter_id},
            )
            self.assertEqual(response.status_code, 200)
            task_id = response.json()["task_id"]
            task = self.client.get(f"/api/tasks/{task_id}").json()
            self.assertEqual(task["status"], "success")
            self.assertEqual(task["type"], "style_analysis")
            self.assertEqual(task["progress"], 100)
            self.assertTrue(task["result"]["profile"]["dimensions"])
            self.assertTrue(task["stage"])
            self.assertTrue(task["logs"])

            response = self.client.post(
                "/api/tasks/knowledge-build/start",
                json={"selected_chapter_id": chapter_id},
            )
            self.assertEqual(response.status_code, 200)
            task = self.client.get(
                f"/api/tasks/{response.json()['task_id']}"
            ).json()
            self.assertEqual(task["status"], "success")
            kb = task["result"]["knowledge_base"]
            self.assertTrue(
                kb["characters"]
                or kb["world_settings"]
                or kb["plot_nodes"]
                or kb["themes"]
            )
        finally:
            settings.anthropic_api_key = original_key

    def test_book_plan_and_auto_next_chapter_persist_files(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        generated_plan = BookPlan(
            source_anchor_chapter_id=chapter_id,
            rough_direction="",
            target_scale="short",
            target_chapter_count=3,
            automation_level="chapter_by_chapter",
            title="自动续写规划",
            premise="承接原作锚点继续推进",
            main_conflict="主角必须在代价与选择之间作出决定",
            tone="克制、紧张",
            ending_direction="完成阶段性选择并留下后续悬念",
            chapters=[
                BookPlanChapter(
                    order=index,
                    title=f"自动章节 {index}",
                    chapter_summary=f"主角完成第 {index} 阶段行动，并承担新的代价。",
                    chapter_goal=f"推动故事进入第 {index} 阶段，并完成关键人物选择",
                    opening_state="承接上一章的行动结果，角色仍处于紧张状态",
                    ending_state="本章目标阶段性完成，但新的风险已经显现",
                    previous_bridge="延续上一章结尾留下的行动线索",
                    next_bridge="把新的异常信号交给下一章继续调查",
                    plot_beats=["承接上一章", "升级冲突", "留下钩子"],
                    chapter_function=["推进主线"],
                    characters=["主角"],
                    conflict="角色目标与现实代价发生正面冲突并迫使其选择",
                    emotional_tone="克制而紧张",
                    ending_hook="新的异常信号出现",
                    target_words=3200,
                    word_count_reason="常规推进章，需容纳行动、冲突与章节钩子",
                )
                for index in range(1, 4)
            ],
            chapter_plans_complete=True,
            model_name="mock-model",
            prompt_chars=1234,
        )
        with patch(
            "app.services.book_planner.conceive_book_plan",
            new=AsyncMock(return_value=generated_plan),
        ):
            response = self.client.post(
                "/api/book-plan/generate",
                json={
                    "source_anchor_chapter_id": chapter_id,
                    "rough_direction": "",
                    "target_scale": "short",
                    "target_chapter_count": 3,
                    "automation_level": "chapter_by_chapter",
                    "auto_create_chapter_plans": True,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        task = self.client.get(f"/api/tasks/{response.json()['task_id']}").json()
        self.assertEqual(task["status"], "success")
        self.assertTrue(planning_store.book_plan_path.exists())

        self.assertTrue(writing_project_store.load_book_plan())
        self.assertFalse(writing_project_store.load_book_plan().accepted)
        plans = [
            item
            for item in self.client.get("/api/chapter-plans").json()
            if item["book_plan_id"] == generated_plan.book_plan_id
        ]
        self.assertEqual(plans, [])

        blocked = self.client.post(
            "/api/chapter-generation/start",
            json={
                "start_chapter_id": chapter_id,
                "source_anchor_chapter_id": chapter_id,
                "plot_direction": "",
                "target_word_count": 600,
                "mode": "chapter",
                "plan_id": "missing_plan",
                "append_to_draft": False,
            },
        )
        self.assertEqual(blocked.status_code, 409)

        accepted = self.client.post("/api/book-plan/accept")
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["accepted"])
        book_plan_records = [
            item
            for item in self.client.get("/api/temp-generations").json()
            if item["record_type"] == "book_plan"
            and item["generation_id"] == generated_plan.book_plan_id
        ]
        self.assertTrue(book_plan_records)
        self.assertTrue(all(item["accepted"] for item in book_plan_records))
        plans = [
            item
            for item in self.client.get("/api/chapter-plans").json()
            if item["book_plan_id"] == generated_plan.book_plan_id
        ]
        self.assertEqual(len(plans), 3)
        first_plan = plans[0]
        draft = self.client.get(f"/api/drafts/{first_plan['draft_id']}").json()
        self.assertEqual(draft["content"], "")

        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        try:
            with patch(
                "app.services.generator.generate_chapter",
                new=AsyncMock(return_value=("自动生成的章节正文", "system")),
            ):
                response = self.client.post(
                    "/api/tasks/generation/start",
                    json={
                        "start_chapter_id": chapter_id,
                        "source_anchor_chapter_id": chapter_id,
                        "plot_direction": "",
                        "target_word_count": 600,
                        "mode": "auto",
                        "draft_id": first_plan["draft_id"],
                        "plan_id": first_plan["plan_id"],
                        "append_to_draft": True,
                        "reference_chapter_ids": [],
                        "pov_character": "",
                        "additional_instructions": "",
                    },
                )
            self.assertEqual(response.status_code, 200, response.text)
            generation_task = self.client.get(
                f"/api/tasks/{response.json()['task_id']}"
            ).json()
            self.assertEqual(generation_task["status"], "success")
            result = generation_task["result"]["generation_result"]
            self.assertTrue(result["accepted"])
            self.assertEqual(result["save_status"], "auto_saved")
            generation_path = Path(result["generation_file_path"]).relative_to(
                "writing_projects/longzu6"
            )
            self.assertTrue(
                writing_project_store.root.joinpath(generation_path).exists()
            )
            self.assertTrue(
                draft_store.root.joinpath(result["saved_draft_path"]).exists()
            )
            self.assertEqual(
                planning_store.get_plan(first_plan["plan_id"]).status,
                "done",
            )
            self.assertTrue(draft_store.list_versions(first_plan["draft_id"]))
        finally:
            settings.anthropic_api_key = original_key

    def test_chapter_plan_fallback_completes_all_eighteen_chapters(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = BookPlan(
            source_anchor_chapter_id=chapter_id,
            target_scale="medium",
            target_chapter_count=18,
            title="十八章规划测试",
            premise="主角沿着失踪线索调查世界树异变。",
            main_conflict="救人与阻止灾难的目标互相冲突。",
            core_theme="选择与代价",
            ending_direction="完成阶段性选择并留下新的时代入口。",
            chapters=[
                BookPlanChapter(
                    order=index,
                    title=f"第 {index} 章",
                    chapter_goal="待补",
                )
                for index in range(1, 19)
            ],
        )
        completer = ChapterPlanCompleter()
        with patch.object(
            completer,
            "_complete_batch",
            new=AsyncMock(return_value=[]),
        ):
            completed, warnings = asyncio.run(completer.complete(plan))

        self.assertTrue(book_plan_chapters_complete(completed))
        self.assertTrue(completed.chapter_plans_complete)
        self.assertEqual(len(completed.chapters), 18)
        self.assertTrue(all(chapter_plan_is_complete(item) for item in completed.chapters))
        self.assertTrue(all(1200 <= item.target_words <= 8000 for item in completed.chapters))
        self.assertEqual(warnings, [])

    def test_chapter_completeness_checks_length_and_sentence_ending(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = ChapterPlan(
            plan_id="quality-plan",
            anchor_chapter_id=chapter_id,
            title="完整性测试章",
            target_words=1200,
            chapter_summary="主角调查异常信号",
            chapter_goal="确认异常信号来源",
            ending_state="主角发现入口",
            next_bridge="下一章进入入口",
            plot_beats=["调查信号", "发现入口", "决定进入"],
        )
        complete = "主角调查异常信号，逐步确认异常信号来源并发现入口。" * 60
        result = check_chapter_completeness(complete, plan)
        self.assertTrue(result.passed)
        self.assertTrue(result.sentence_complete)

        incomplete = check_chapter_completeness("主角刚要开口，但是", plan)
        self.assertFalse(incomplete.passed)
        self.assertFalse(incomplete.sentence_complete)
        self.assertIn(
            "incomplete_ending",
            {item.code for item in incomplete.issues},
        )

    def test_incomplete_ending_keeps_usable_text_and_truncates_safely(self) -> None:
        source = "他推开门。\n走廊里没有人。\n手机又震了一下，屏幕上只有两个字："
        truncated = truncate_to_complete_sentence(source)
        self.assertEqual(truncated, "他推开门。\n走廊里没有人。")

        result = ensure_complete_ending(source)
        self.assertEqual(result.status, "truncated")
        self.assertEqual(result.text, truncated)

        partial = ensure_complete_ending("未完成正文" * 61)
        self.assertEqual(partial.status, "partial")
        self.assertTrue(partial.warning)

        failed = ensure_complete_ending("太短而且")
        self.assertEqual(failed.status, "failed")

    def test_model_repair_failure_returns_partial_for_usable_text(self) -> None:
        endings = []
        generator = ContinuationGenerator(ending_callback=endings.append)
        generator._generate_draft = AsyncMock(return_value="")
        result = asyncio.run(
            generator._ensure_complete_ending(
                "这是一段尚未收束的正文" * 35,
                "system",
                final_segment=True,
                allow_model_repair=True,
                repair_progress=80,
            )
        )
        self.assertEqual(result.status, "partial")
        self.assertEqual(endings[-1].status, "partial")

    def test_slightly_over_limit_is_warning_and_can_be_saved(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = ChapterPlan(
            plan_id="slight-over-limit-plan",
            anchor_chapter_id=chapter_id,
            title="轻微超长测试章",
            target_words=5000,
        )
        content = ("字" * 8085) + "。"
        check = check_chapter_completeness(content, plan)
        self.assertTrue(check.passed)
        self.assertTrue(check.can_save_official)
        self.assertEqual(check.blocking_errors, [])
        self.assertIn(
            "chapter_above_recommended",
            {item.code for item in check.warnings},
        )

        temp_response = self.client.post(
            "/api/chapter-generation/save-temp",
            json={
                "generation_id": "slight-over-limit-generation",
                "chapter_order": 96,
                "chapter_title": plan.title,
                "content": content,
                "generation_request": {
                    "_completeness_check": check.model_dump(mode="json"),
                },
            },
        )
        self.assertEqual(temp_response.status_code, 200, temp_response.text)
        official_response = self.client.post(
            "/api/chapter-generation/save-official",
            json={
                "title": plan.title,
                "content": content,
                "chapter_order": 96,
                "source_generation_id": "slight-over-limit-generation",
                "source_temp_id": temp_response.json()["temp_id"],
                "completeness_check": check.model_dump(mode="json"),
            },
        )
        self.assertEqual(official_response.status_code, 200, official_response.text)
        official = official_response.json()
        self.assertTrue(official["saved_with_warnings"])
        self.assertTrue(official["warnings"])

    def test_legacy_slight_over_limit_error_does_not_block_save(self) -> None:
        content = ("字" * 8085) + "。"
        temp_response = self.client.post(
            "/api/chapter-generation/save-temp",
            json={
                "generation_id": "legacy-over-limit-generation",
                "chapter_order": 97,
                "chapter_title": "旧检查兼容章",
                "content": content,
                "generation_request": {
                    "_completeness_check": {
                        "passed": False,
                        "word_count": 8086,
                        "maximum_word_count": 8000,
                        "issues": [
                            {
                                "level": "error",
                                "code": "chapter_too_long",
                                "message": "正文 8086 字，超过本章合理上限 8000 字。",
                            }
                        ],
                    },
                },
            },
        )
        response = self.client.post(
            "/api/chapter-generation/save-official",
            json={
                "title": "旧检查兼容章",
                "content": content,
                "chapter_order": 97,
                "source_temp_id": temp_response.json()["temp_id"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_local_revision_edits_preserve_unmodified_chapter(self) -> None:
        original = "第一段保持不变。\n\n第二段冲突较弱。\n\n第三段结尾保持不变。"
        revised, applied = _apply_revision_edits(
            original,
            [
                {
                    "search": "第二段冲突较弱。",
                    "replacement": "第二段里警报突然响起，冲突明显增强。",
                }
            ],
        )
        self.assertEqual(applied, 1)
        self.assertIn("第一段保持不变。", revised)
        self.assertIn("第三段结尾保持不变。", revised)
        self.assertNotIn("第二段冲突较弱。", revised)

    def test_local_revision_model_returns_patch_not_short_chapter(self) -> None:
        original = (
            "开头保持不变。\n\n"
            + ("这一段承载原章节的剧情、人物和描写，必须继续保留。\n\n" * 180)
            + "这里的冲突较弱。\n\n结尾保持不变。"
        )
        generator = ContinuationGenerator()
        generator._call_revision_model = AsyncMock(
            return_value=json.dumps(
                {
                    "edits": [
                        {
                            "search": "这里的冲突较弱。",
                            "replacement": "警报与脚步声同时逼近，这里的冲突骤然升级。",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )
        revised, _, _ = asyncio.run(
            generator._iterate_local_edit(
                original,
                "小幅增强冲突",
                "这里的冲突较弱。",
                "",
            )
        )
        self.assertGreater(len(revised), len(original) * 0.95)
        self.assertIn("开头保持不变。", revised)
        self.assertIn("结尾保持不变。", revised)
        self.assertIn("冲突骤然升级", revised)

    def test_revision_diagnostics_reject_abnormal_shortening(self) -> None:
        original = ("完整章节内容。" * 1000)
        short = ("短版内容。" * 100)
        diagnostics = _revision_diagnostics(
            original,
            short,
            "小幅增强冲突",
            "full_rewrite",
        )
        self.assertTrue(diagnostics.revision_failed)
        self.assertTrue(diagnostics.requires_confirmation)
        self.assertEqual(diagnostics.change_level, "异常缩短")

        compressed = _revision_diagnostics(
            original,
            short,
            "请压缩成摘要",
            "full_rewrite",
        )
        self.assertFalse(compressed.revision_failed)

    def test_ai_review_can_semantically_override_keyword_warnings(self) -> None:
        from app.services.chapter_reviewer import ChapterReviewService

        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = ChapterPlan(
            plan_id="ai-review-plan",
            anchor_chapter_id=chapter_id,
            title="隐喻覆盖测试",
            target_words=1200,
            chapter_summary="发现世界树入口，决定进入",
            chapter_goal="用含蓄方式完成关键选择",
            opening_state="主角仍在入口之外犹豫",
            ending_state="主角已经跨过入口",
            previous_bridge="承接上一章留下的门扉线索",
            next_bridge="下一章从门后的黑暗世界开始",
            plot_beats=["发现入口", "作出选择", "跨过门槛"],
            chapter_function=["推进主线"],
            characters=["主角"],
            conflict="主角必须在安全与真相之间作出选择",
            emotional_tone="克制而紧张",
            word_count_reason="推进章需要完整呈现犹豫、选择和行动结果",
        )
        content = (
            "他没有说自己找到了入口，只把手按在那道没有门框的阴影上。"
            "身后的灯一盏盏熄灭，他终于松开扶墙的手，向前迈了一步。"
            "黑暗合拢时，旧世界的风停在了他的背后。"
        ) * 20
        rule_check = check_chapter_completeness(content, plan)
        self.assertIn(
            "summary_alignment",
            {item.code for item in rule_check.issues},
        )
        payload = {
            "overall_pass": True,
            "score": 91,
            "summary_alignment": "正文以阴影和迈步隐喻发现并进入入口，语义完成摘要。",
            "summary_aligned": True,
            "plot_beats_coverage": [
                {"beat": beat, "covered": True, "evidence": "向前迈了一步", "comment": "隐喻覆盖"}
                for beat in plan.plot_beats
            ],
            "ending_state_alignment": "结尾已进入门后空间。",
            "ending_state_aligned": True,
            "continuity_with_previous": "承接门扉线索。",
            "continuity_previous_pass": True,
            "continuity_with_next": "黑暗世界可直接作为下一章开场。",
            "continuity_next_pass": True,
            "character_consistency": "选择过程自然。",
            "character_consistent": True,
            "style_consistency": "表达克制。",
            "style_consistent": True,
            "problems": [],
            "repair_suggestions": [],
            "need_repair": False,
        }
        constructor_kwargs: list[dict] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                constructor_kwargs.append(kwargs)
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **_kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=json.dumps(payload, ensure_ascii=False),
                    )
                ]
            )

        with (
            patch("app.services.chapter_reviewer.Anthropic", FakeAnthropic),
            patch(
                "app.services.chapter_reviewer.asyncio.to_thread",
                new=fake_to_thread,
            ),
        ):
            report = asyncio.run(
                ChapterReviewService().review(
                    generation_id="generation-test",
                    content=content,
                    plan=plan,
                    book_plan=None,
                    previous_chapter_tail="",
                    next_plan=None,
                    knowledge_base=KnowledgeBase(),
                    rule_check=rule_check,
                )
            )
        self.assertTrue(report.overall_pass)
        self.assertTrue(report.summary_aligned)
        self.assertTrue(report.semantic_overrides)
        self.assertEqual(constructor_kwargs[0]["max_retries"], 0)

    def test_ai_review_parser_accepts_json_markdown_and_reasoning_blocks(self) -> None:
        structured = {
            "overall_pass": True,
            "score": 88,
            "summary_alignment": "语义上符合章节规划。",
            "plot_beats_coverage": [],
        }
        direct = parse_quality_check_response(structured)
        self.assertEqual(direct.structured_report, structured)
        self.assertIsNone(direct.parse_warning)

        fenced = parse_quality_check_response(
            "下面是报告：\n```json\n"
            + json.dumps(structured, ensure_ascii=False)
            + "\n```"
        )
        self.assertEqual(fenced.structured_report["score"], 88)

        markdown = parse_quality_check_response(
            "# AI 深度质检报告\n\n## 总体结论\n建议小修后保存。"
        )
        self.assertIsNone(markdown.structured_report)
        self.assertIn("建议小修后保存", markdown.readable_report)
        self.assertIn("非 JSON", markdown.parse_warning)

        thinking_only = parse_quality_check_response(
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="thinking",
                        thinking="# AI 深度质检报告\n\n人物动机基本成立。",
                    )
                ]
            )
        )
        self.assertIsNone(thinking_only.structured_report)
        self.assertIn("人物动机基本成立", thinking_only.readable_report)
        self.assertIn("人物动机基本成立", thinking_only.raw_response)

        reasoning_only = parse_quality_check_response(
            {"reasoning_content": "普通文本质检：结尾衔接需要加强。"}
        )
        self.assertIn("结尾衔接需要加强", reasoning_only.readable_report)

    def test_ai_review_text_fallback_finishes_with_warning(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = planning_store.create_plan(
            ChapterPlanInput(
                title="文本质检兜底测试",
                order=89,
                anchor_chapter_id=chapter_id,
                target_words=1200,
                chapter_summary="主角调查并获得线索",
                chapter_goal="保留下一章入口",
                ending_state="主角获得线索",
                plot_beats=["调查", "获得线索"],
            )
        )
        report = AIChapterReviewResult(
            plan_id=plan.plan_id,
            generation_id="text-review-generation",
            report_format="text",
            readable_report="# AI 深度质检报告\n\n建议小修后保存。",
            raw_response="模型原始文本",
            parse_warning="AI 质检返回了非 JSON 格式，已按文本报告展示",
        )
        with patch(
            "app.services.chapter_reviewer.ChapterReviewService.review",
            new=AsyncMock(return_value=report),
        ):
            response = self.client.post(
                "/api/chapter-generation/ai-review/start",
                json={
                    "generation_id": "",
                    "plan_id": plan.plan_id,
                    "content": "主角调查现场并拿到了关键线索。下一步目标已经明确。" * 30,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        review_task = self.client.get(
            f"/api/tasks/{response.json()['task_id']}"
        ).json()
        self.assertEqual(review_task["status"], "partial_success")
        self.assertIn("建议小修后保存", review_task["result"]["readable_report"])
        self.assertIsNone(review_task["result"]["structured_report"])
        self.assertIn("非 JSON", review_task["result"]["parse_warning"])

    def test_ai_review_and_repair_tasks_finish_and_preserve_original(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = planning_store.create_plan(
            ChapterPlanInput(
                title="AI 质检任务测试",
                order=88,
                anchor_chapter_id=chapter_id,
                target_words=1200,
                chapter_summary="主角完成调查并取得证据",
                chapter_goal="完成调查并留下下一章入口",
                opening_state="主角刚抵达调查地点",
                ending_state="主角已经取得关键证据",
                previous_bridge="承接上一章给出的调查坐标",
                next_bridge="下一章根据证据追踪幕后人物",
                plot_beats=["抵达地点", "完成调查", "取得证据"],
                chapter_function=["推进主线"],
                characters=["主角"],
                conflict="主角必须在暴露身份前取得证据",
                emotional_tone="紧张克制",
                word_count_reason="调查推进章需要完整行动与结果",
            )
        )
        original = "这是不会被覆盖的原始章节正文。"
        report = AIChapterReviewResult(
            plan_id=plan.plan_id,
            generation_id="source-generation",
            overall_pass=False,
            score=62,
            summary_alignment="调查过程不完整。",
            plot_beats_coverage=[
                PlotBeatReview(beat=beat, covered=False)
                for beat in plan.plot_beats
            ],
            ending_state_alignment="尚未取得证据。",
            continuity_with_previous="可以承接。",
            continuity_with_next="缺少证据线索。",
            character_consistency="基本一致。",
            style_consistency="基本一致。",
            problems=["缺少取得证据的结果"],
            repair_suggestions=["在结尾补足取得证据并引出幕后人物"],
            need_repair=True,
        )
        with patch(
            "app.services.chapter_reviewer.ChapterReviewService.review",
            new=AsyncMock(return_value=report),
        ):
            response = self.client.post(
                "/api/chapter-generation/ai-review/start",
                json={
                    "generation_id": "source-generation",
                    "plan_id": plan.plan_id,
                    "content": original,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        review_task = self.client.get(
            f"/api/tasks/{response.json()['task_id']}"
        ).json()
        self.assertEqual(review_task["status"], "success")

        repaired = (
            "主角抵达调查地点后避开监控，逐层检查异常痕迹，最终从暗格中取得关键证据。"
            "证据末尾留下幕后人物的坐标，下一步追踪方向已经明确。"
        ) * 30
        with patch(
            "app.services.chapter_reviewer.ChapterReviewService.repair",
            new=AsyncMock(return_value=repaired),
        ):
            response = self.client.post(
                "/api/chapter-generation/ai-repair/start",
                json={
                    "generation_id": "source-generation",
                    "plan_id": plan.plan_id,
                    "content": original,
                    "review_report": report.model_dump(mode="json"),
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        repair_task = self.client.get(
            f"/api/tasks/{response.json()['task_id']}"
        ).json()
        self.assertEqual(repair_task["status"], "success")
        self.assertEqual(repair_task["result"]["generation_result"]["content"], repaired)
        temp = repair_task["result"]["temp_generation"]
        self.assertEqual(temp["record_type"], "ai_repair")
        self.assertNotEqual(temp["content"], original)
        self.assertEqual(original, "这是不会被覆盖的原始章节正文。")

    def test_failed_completeness_cannot_enter_official_library(self) -> None:
        temp_response = self.client.post(
            "/api/chapter-generation/save-temp",
            json={
                "chapter_order": 1,
                "chapter_title": "未完成章节",
                "content": "正文在这里中断，但是",
                "generation_request": {
                    "_completeness_check": {
                        "passed": False,
                        "sentence_complete": False,
                    }
                },
            },
        )
        self.assertEqual(temp_response.status_code, 200, temp_response.text)
        response = self.client.post(
            "/api/chapter-generation/save-official",
            json={
                "title": "未完成章节",
                "content": "正文在这里中断，但是",
                "chapter_order": 1,
                "source_temp_id": temp_response.json()["temp_id"],
            },
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_book_plan_parser_accepts_common_model_wrappers(self) -> None:
        from app.services.model_response_parser import parse_model_json_response

        strict, _, strict_error = parse_model_json_response(
            '{"title":"龙族 VI","chapters":[]}'
        )
        self.assertEqual(strict["title"], "龙族 VI")
        self.assertIsNone(strict_error)

        fenced, _, fenced_error = parse_model_json_response(
            '说明如下：\n```json\n{"title":"代码块","chapters":[],}\n```\n请审核。'
        )
        self.assertEqual(fenced["title"], "代码块")
        self.assertIsNone(fenced_error)

        wrapped, _, wrapped_error = parse_model_json_response(
            '先给结论。\n{"title":"前后文字","chapters":[]}\n以上。'
        )
        self.assertEqual(wrapped["title"], "前后文字")
        self.assertIsNone(wrapped_error)

        blocks, text, blocks_error = parse_model_json_response(
            SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking="内部推理"),
                    SimpleNamespace(
                        type="text",
                        text='﻿{“title”:“中文引号”,“chapters”:[]}',
                    ),
                ]
            )
        )
        self.assertEqual(blocks["title"], "中文引号")
        self.assertNotIn("内部推理", text)
        self.assertIsNone(blocks_error)

        truncated, _, truncated_error = parse_model_json_response(
            '{"title":"被截断","chapter_count":18,"chapters":['
            '{"title":"第一章","summary":"简介在这里中断'
        )
        self.assertEqual(truncated["title"], "被截断")
        self.assertEqual(truncated["chapters"][0]["summary"], "简介在这里中断")
        self.assertIsNone(truncated_error)

    def test_book_plan_normalization_tolerates_partial_fields(self) -> None:
        from app.services.book_planner import normalize_book_plan_payload

        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        plan = normalize_book_plan_payload(
            {
                "character_arcs": {"路明非": "承担选择"},
                "foreshadowing_plan": "回收旧谜团",
                "major_plotlines": {"主线": "寻找失踪者"},
                "chapters": [
                    {"title": "第一章", "summary": "异常信号再次出现"},
                    {"title": "第二章"},
                ],
            },
            BookPlanGenerateRequest(
                source_anchor_chapter_id=chapter_id,
                target_chapter_count=18,
            ),
            raw_text="模型返回的原始构想摘要",
        )
        self.assertEqual(plan.title, "龙族 VI：未命名续写")
        self.assertEqual(plan.target_chapter_count, 2)
        self.assertEqual(len(plan.chapters), 2)
        self.assertEqual(plan.chapters[0].chapter_goal, "异常信号再次出现")
        self.assertTrue(plan.character_arcs)
        self.assertEqual(plan.foreshadowing, ["回收旧谜团"])
        self.assertTrue(plan.main_conflict)

    def test_book_plan_parse_failure_preserves_raw_response(self) -> None:
        from app.services.book_planner import BookPlanParseError

        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        raw_text = "这是模型已经返回、但无法结构化的总体构想正文。"
        with patch(
            "app.services.book_planner.conceive_book_plan",
            new=AsyncMock(
                side_effect=BookPlanParseError(
                    "模型返回文本 JSON 解析失败：未找到完整 JSON 对象",
                    raw_text=raw_text,
                    prompt_chars=2345,
                )
            ),
        ):
            response = self.client.post(
                "/api/book-plan/generate",
                json={
                    "source_anchor_chapter_id": chapter_id,
                    "rough_direction": "",
                    "target_scale": "medium",
                    "target_chapter_count": 18,
                    "automation_level": "chapter_by_chapter",
                    "auto_create_chapter_plans": False,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        task = self.client.get(f"/api/tasks/{response.json()['task_id']}").json()
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["result"]["raw_book_plan_text"], raw_text)
        self.assertTrue(task["result"]["raw_temp_id"].startswith("book_plan_raw_"))
        raw_id = task["result"]["raw_temp_id"]
        self.assertTrue((writing_project_store.temp_dir / f"{raw_id}.md").exists())
        self.assertTrue((writing_project_store.temp_dir / f"{raw_id}.json").exists())
        stored = self.client.get(f"/api/temp-generations/{raw_id}")
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertEqual(stored.json()["content"], raw_text)

    def test_raw_book_plan_can_be_reparsed_and_saved(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        record = writing_project_store.save_raw_book_plan(
            raw_text=(
                "模型说明：\n```json\n"
                '{"title":"龙族 VI：重解析",'
                '"premise":"从旧冲突继续推进",'
                '"chapters":[{"title":"第一章","summary":"新的信号出现"}]}'
                "\n```"
            ),
            request={
                "source_anchor_chapter_id": chapter_id,
                "rough_direction": "",
                "target_scale": "medium",
                "target_chapter_count": 18,
                "automation_level": "chapter_by_chapter",
            },
            error_message="旧解析器未识别代码块",
            model_name="mock-model",
            prompt_chars=1000,
        )
        response = self.client.post(
            f"/api/book-plan/reparse-raw/{record.temp_id}"
        )
        self.assertEqual(response.status_code, 200, response.text)
        plan = response.json()
        self.assertEqual(plan["title"], "龙族 VI：重解析")
        self.assertEqual(len(plan["chapters"]), 1)
        self.assertTrue(
            (writing_project_store.book_plan_dir / "longzu6_plan.json").exists()
        )
        self.assertTrue(
            (writing_project_store.book_plan_dir / "longzu6_plan.md").exists()
        )

    def test_temp_and_official_chapter_storage_are_isolated(self) -> None:
        temp_response = self.client.post(
            "/api/chapter-generation/save-temp",
            json={
                "generation_id": "storage-test",
                "chapter_order": 42,
                "chapter_title": "隔离测试章",
                "record_type": "manual_snapshot",
                "content": "这是临时正文。",
            },
        )
        self.assertEqual(temp_response.status_code, 200, temp_response.text)
        temp_record = temp_response.json()

        official_response = self.client.post(
            "/api/chapter-generation/save-official",
            json={
                "title": "隔离测试章",
                "content": "这是正式正文。",
                "chapter_order": 42,
                "source_generation_id": "storage-test",
                "source_temp_id": temp_record["temp_id"],
            },
        )
        self.assertEqual(official_response.status_code, 200, official_response.text)
        official = official_response.json()
        self.assertEqual(official["chapter_id"], "chapter_042")
        self.assertTrue(
            (writing_project_store.official_dir / "chapter_042.md").exists()
        )
        marked_temp = self.client.get(
            f"/api/temp-generations/{temp_record['temp_id']}"
        ).json()
        self.assertTrue(marked_temp["saved_official"])

        deleted_temp = self.client.delete(
            f"/api/temp-generations/{temp_record['temp_id']}"
        )
        self.assertEqual(deleted_temp.status_code, 200, deleted_temp.text)
        still_official = self.client.get("/api/official-chapters/chapter_042")
        self.assertEqual(still_official.status_code, 200, still_official.text)
        self.assertEqual(still_official.json()["content"], "这是正式正文。")

        updated = self.client.put(
            "/api/official-chapters/chapter_042",
            json={"title": "隔离测试章（修订）", "content": "这是修订后的正文。"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["revision_count"], 1)
        self.assertTrue(
            (writing_project_store.revisions_dir / "chapter_042_v1.md").exists()
        )

    def test_long_task_generation_success_and_timeout_failure(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0]["chapter_id"]
        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        generation_router._knowledge_base = KnowledgeBase(
            themes=[Theme(name="测试主题", description="任务接口验收")]
        )
        payload = {
            "start_chapter_id": chapter_id,
            "plot_direction": "继续当前冲突",
            "target_word_count": 500,
            "pov_character": "",
            "additional_instructions": "",
        }
        try:
            with patch(
                "app.services.generator.generate_chapter",
                new=AsyncMock(return_value=("任务生成正文", "system")),
            ):
                response = self.client.post(
                    "/api/tasks/generation/start",
                    json=payload,
                )
            self.assertEqual(response.status_code, 200)
            task = self.client.get(
                f"/api/tasks/{response.json()['task_id']}"
            ).json()
            self.assertEqual(task["status"], "success")
            self.assertEqual(
                task["result"]["generation_result"]["content"],
                "任务生成正文",
            )

            with patch(
                "app.services.generator.generate_chapter",
                new=AsyncMock(
                    side_effect=GenerationServiceError("模型请求超时")
                ),
            ):
                response = self.client.post(
                    "/api/tasks/generation/start",
                    json=payload,
                )
            task = self.client.get(
                f"/api/tasks/{response.json()['task_id']}"
            ).json()
            self.assertEqual(task["status"], "failed")
            self.assertTrue(task["error"]["is_timeout"])
            self.assertEqual(
                task["message"],
                "模型请求超时，请检查网络/API 服务或稍后重试",
            )
        finally:
            settings.anthropic_api_key = original_key

    def test_task_list_and_soft_cancel(self) -> None:
        created = task_manager.create(TaskType.REVISION, {"source": "test"})
        response = self.client.post(f"/api/tasks/{created.task_id}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")
        tasks = self.client.get("/api/tasks?limit=200").json()
        self.assertIn(created.task_id, {task["task_id"] for task in tasks})

    def test_model_calls_disable_retries_and_use_hard_timeout(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.generator import generate_chapter
        from app.services.knowledge_base import build_kb
        from app.services.style_analyzer import analyze_chapter

        constructor_kwargs: list[dict] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                constructor_kwargs.append(kwargs)
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        chapter = next(iter(_corpus_store.values()))
        chapters = list(_corpus_store.values())
        original_key = settings.anthropic_api_key
        original_timeout = settings.model_timeout_seconds
        settings.anthropic_api_key = "configured-for-test"
        settings.model_timeout_seconds = 0.02
        try:
            with (
                patch("app.services.style_analyzer.Anthropic", FakeAnthropic),
                patch(
                    "app.services.style_analyzer.asyncio.to_thread",
                    new=never_returns,
                ),
            ):
                style = asyncio.run(analyze_chapter(chapter))
            self.assertTrue(style)
            self.assertTrue(all(item.summary for item in style))

            with (
                patch("app.services.knowledge_base.Anthropic", FakeAnthropic),
                patch(
                    "app.services.knowledge_base.asyncio.to_thread",
                    new=never_returns,
                ),
            ):
                kb = asyncio.run(build_kb(chapters))
            self.assertTrue(
                kb.characters
                or kb.world_settings
                or kb.plot_nodes
                or kb.themes
            )

            with (
                patch("app.services.generator.Anthropic", FakeAnthropic),
                patch(
                    "app.services.generator.asyncio.to_thread",
                    new=never_returns,
                ),
            ):
                with self.assertRaises(GenerationServiceError):
                    asyncio.run(
                        generate_chapter(
                            chapter=chapter,
                            kb=KnowledgeBase(
                                themes=[
                                    Theme(
                                        name="测试主题",
                                        description="硬超时测试",
                                    )
                                ]
                            ),
                            request=GenerationRequest(
                                start_chapter_id=chapter.chapter_id,
                                plot_direction="继续当前冲突",
                                target_word_count=300,
                            ),
                        )
                    )

            self.assertEqual(len(constructor_kwargs), 3)
            self.assertTrue(
                all(item.get("max_retries") == 0 for item in constructor_kwargs)
            )
        finally:
            settings.anthropic_api_key = original_key
            settings.model_timeout_seconds = original_timeout

    def test_model_response_text_skips_thinking_blocks(self) -> None:
        from app.services.generator import _response_text as generation_text
        from app.services.knowledge_base import _response_text as knowledge_text
        from app.services.style_analyzer import _response_text as style_text

        response = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking"),
                SimpleNamespace(type="text", text="有效正文"),
            ]
        )
        self.assertEqual(generation_text(response), "有效正文")
        self.assertEqual(knowledge_text(response), "有效正文")
        self.assertEqual(style_text(response), "有效正文")

    def test_dimension_examples_accept_list_dict_string_and_empty(self) -> None:
        base = {
            "dimension": AnalysisDimension.CLIFFHANGER_STYLE,
            "summary": "测试摘要",
        }
        self.assertEqual(
            DimensionResult(**base, examples=["示例一"]).examples,
            ["示例一"],
        )
        self.assertEqual(
            DimensionResult(
                **base,
                examples={"悬念式结尾示例": "烧，无人能见。"},
            ).examples,
            ["悬念式结尾示例：烧，无人能见。"],
        )
        self.assertEqual(
            DimensionResult(**base, examples="单个示例").examples,
            ["单个示例"],
        )
        self.assertEqual(DimensionResult(**base, examples=None).examples, [])

    def test_light_generation_uses_one_bounded_model_call(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.generator import generate_chapter

        calls: list[dict] = []
        progress_messages: list[str] = []
        constructor_kwargs: list[dict] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                constructor_kwargs.append(kwargs)
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="小规模测试正文")]
            )

        source_chapter = next(iter(_corpus_store.values()))
        long_chapter = source_chapter.model_copy(
            update={"content": source_chapter.content + ("测试上下文" * 2000)}
        )
        kb = KnowledgeBase(
            characters=[
                CharacterProfile(
                    name=f"角色{index}",
                    personality="谨慎但坚定" * 30,
                    speech_style="简短直接" * 20,
                )
                for index in range(8)
            ],
            world_settings=[
                WorldSetting(
                    category="location",
                    name=f"地点{index}",
                    description="重要世界设定" * 40,
                )
                for index in range(6)
            ],
            themes=[Theme(name="孤独", description="测试主题")],
        )
        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        try:
            with (
                patch("app.services.generator.Anthropic", FakeAnthropic),
                patch(
                    "app.services.generator.asyncio.to_thread",
                    new=fake_to_thread,
                ),
            ):
                content, _system_prompt = asyncio.run(
                    generate_chapter(
                        chapter=long_chapter,
                        kb=kb,
                        request=GenerationRequest(
                            start_chapter_id=long_chapter.chapter_id,
                            plot_direction="收到一条改变局势的短消息",
                            target_word_count=300,
                        ),
                        progress_callback=lambda _progress, _stage, message: (
                            progress_messages.append(message)
                        ),
                    )
                )
        finally:
            settings.anthropic_api_key = original_key

        self.assertEqual(content, "小规模测试正文")
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0]["max_tokens"], 800)
        self.assertEqual(
            calls[0]["timeout"],
            settings.generation_timeout_seconds,
        )
        prompt_chars = len(calls[0]["system"]) + len(
            calls[0]["messages"][0]["content"]
        )
        self.assertLessEqual(prompt_chars, settings.generation_prompt_max_chars)
        self.assertTrue(
            any("Prompt 字符数：" in message for message in progress_messages)
        )
        self.assertEqual(constructor_kwargs[0]["max_retries"], 0)

    def test_draft_project_lifecycle_uses_isolated_files(self) -> None:
        chapter = self.client.get("/api/corpus/chapters").json()[0]
        source_path = BACKEND_DIR / chapter["source_file"]
        source_before = (
            source_path.read_bytes()
            if source_path.exists()
            else b""
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DraftStore(Path(temp_dir) / "longzu_continuation")
            with (
                patch("app.routers.drafts.draft_store", store),
                patch("app.services.draft_store.draft_store", store),
            ):
                created = self.client.post(
                    "/api/drafts",
                    json={
                        "title": "验收草稿",
                        "source_anchor_chapter_id": chapter["chapter_id"],
                        "notes": "本地文件验收",
                    },
                )
                self.assertEqual(created.status_code, 200, created.text)
                draft_id = created.json()["draft_id"]
                saved = self.client.put(
                    f"/api/drafts/{draft_id}",
                    json={
                        "title": "验收草稿",
                        "content": "第一段正文。",
                        "notes": "本地文件验收",
                    },
                )
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertGreater(saved.json()["word_count"], 0)

                version = self.client.post(f"/api/drafts/{draft_id}/version")
                self.assertEqual(version.status_code, 200, version.text)
                appended = self.client.post(
                    f"/api/drafts/{draft_id}/append",
                    json={
                        "generated_text": "第二段生成正文。",
                        "generation_id": "",
                    },
                )
                self.assertEqual(appended.status_code, 200, appended.text)
                self.assertIn("第二段生成正文", appended.json()["content"])
                self.assertGreater(
                    appended.json()["word_count"],
                    saved.json()["word_count"],
                )
                versions = self.client.get(
                    f"/api/drafts/{draft_id}/versions"
                )
                self.assertEqual(versions.status_code, 200)
                self.assertGreaterEqual(len(versions.json()), 2)
                exported = self.client.post(
                    f"/api/drafts/{draft_id}/export",
                    json={"format": "md"},
                )
                self.assertEqual(exported.status_code, 200, exported.text)
                self.assertIn("第二段生成正文", exported.text)
                manifest = json.loads(
                    (store.root / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["chapters"][0]["draft_id"], draft_id)
                self.assertTrue(
                    (store.root / "drafts" / f"{draft_id}.md").exists()
                )
        if source_path.exists():
            self.assertEqual(source_path.read_bytes(), source_before)

    def test_outline_chapter_plan_and_continuity_apis_persist(self) -> None:
        chapter = self.client.get("/api/corpus/chapters").json()[0]
        outline = self.client.put(
            "/api/outline",
            json={
                "title": "验收续写工程",
                "premise": "围绕失踪线索展开后续故事",
                "main_conflict": "主角必须在信任与真相之间选择",
                "tone": "克制、悬疑",
                "ending_direction": "揭示部分真相但保留更大危机",
                "continuity_notes": ["不改变已确认角色关系"],
                "foreshadowing": ["旧车票上的编号"],
                "character_arcs": ["主角从逃避转向承担"],
                "prohibitions": ["不要复活已确认死亡角色"],
            },
        )
        self.assertEqual(outline.status_code, 200, outline.text)
        self.assertEqual(
            json.loads(
                planning_store.outline_path.read_text(encoding="utf-8")
            )["premise"],
            "围绕失踪线索展开后续故事",
        )

        first_draft = self.client.post(
            "/api/drafts",
            json={
                "title": "规划验收章",
                "source_anchor_chapter_id": chapter["chapter_id"],
                "notes": "",
            },
        )
        self.assertEqual(first_draft.status_code, 200, first_draft.text)
        draft_id = first_draft.json()["draft_id"]
        plan_payload = {
            "draft_id": draft_id,
            "title": "第一章规划",
            "order": 1,
            "anchor_chapter_id": chapter["chapter_id"],
            "chapter_goal": "找到旧车票编号的来源",
            "plot_beats": ["发现车票", "追查编号", "遭遇阻拦"],
            "chapter_function": ["推进主线", "埋伏笔"],
            "characters": ["主角"],
            "conflict": "是否相信陌生人的警告",
            "foreshadowing_to_plant": ["编号与学院有关"],
            "foreshadowing_to_resolve": [],
            "ending_hook": "电话另一端传来熟悉的声音",
            "status": "planned",
        }
        created = self.client.post("/api/chapter-plans", json=plan_payload)
        self.assertEqual(created.status_code, 200, created.text)
        plan_id = created.json()["plan_id"]
        self.assertTrue(planning_store.plans_path.exists())
        plan_payload["status"] = "drafting"
        updated = self.client.put(
            f"/api/chapter-plans/{plan_id}",
            json=plan_payload,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "drafting")

        duplicate = self.client.post(
            "/api/drafts",
            json={
                "title": "规划验收章",
                "source_anchor_chapter_id": chapter["chapter_id"],
                "notes": "",
            },
        )
        self.assertEqual(duplicate.status_code, 200)
        check = self.client.post(
            f"/api/drafts/{draft_id}/continuity-check"
        )
        self.assertEqual(check.status_code, 200, check.text)
        codes = {item["code"] for item in check.json()["issues"]}
        self.assertIn("empty_draft", codes)
        self.assertIn("duplicate_title", codes)

        deleted = self.client.delete(f"/api/chapter-plans/{plan_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(
            self.client.get(f"/api/drafts/{draft_id}").status_code,
            200,
        )

    def test_generation_prompt_includes_compact_project_plan_context(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.generator import generate_chapter

        chapter = next(iter(_corpus_store.values()))
        draft = draft_store.create_draft(
            title="上下文验收章",
            source_anchor_chapter_id=chapter.chapter_id,
        )
        plan = planning_store.create_plan(
            ChapterPlanInput(
                draft_id=draft.draft_id,
                title="上下文规划",
                order=2,
                anchor_chapter_id=chapter.chapter_id,
                chapter_goal="保护旧车票上的秘密编号",
                plot_beats=["调查编号", "遭遇追踪"],
                chapter_function=["推进主线", "埋伏笔"],
                conflict="是否公开编号",
                ending_hook="陌生电话说出编号",
            )
        )
        calls: list[dict] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="规划上下文测试正文")]
            )

        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        try:
            with (
                patch("app.services.generator.Anthropic", FakeAnthropic),
                patch(
                    "app.services.generator.asyncio.to_thread",
                    new=fake_to_thread,
                ),
            ):
                content, _ = asyncio.run(
                    generate_chapter(
                        chapter=chapter,
                        kb=KnowledgeBase(
                            themes=[Theme(name="连续性", description="验收")]
                        ),
                        request=GenerationRequest(
                            start_chapter_id=chapter.chapter_id,
                            plot_direction="继续调查",
                            target_word_count=300,
                            mode="single",
                            draft_id=draft.draft_id,
                            plan_id=plan.plan_id,
                        ),
                        draft_content="当前草稿末尾内容",
                        previous_draft_content="上一章草稿结尾内容",
                        planning_context=planning_store.compact_context(
                            plan.plan_id
                        ),
                    )
                )
        finally:
            settings.anthropic_api_key = original_key

        self.assertEqual(content, "规划上下文测试正文")
        prompt = calls[0]["messages"][0]["content"]
        self.assertIn("项目总纲摘要", prompt)
        self.assertIn("当前章节规划", prompt)
        self.assertIn("保护旧车票上的秘密编号", prompt)
        self.assertIn("当前草稿末尾内容", prompt)
        self.assertIn("上一章草稿结尾内容", prompt)
        self.assertLessEqual(
            len(calls[0]["system"]) + len(prompt),
            settings.generation_prompt_max_chars,
        )

    def test_segmented_generation_failure_preserves_partial_task_result(self) -> None:
        chapter_id = self.client.get("/api/corpus/chapters").json()[0][
            "chapter_id"
        ]
        generation_router._knowledge_base = KnowledgeBase(
            themes=[Theme(name="测试主题", description="分段任务验收")]
        )
        calls: list[dict] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="text",
                            text="第一段已生成正文。" * 40,
                        )
                    ]
                )
            raise TimeoutError("segment timeout")

        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DraftStore(Path(temp_dir) / "longzu_continuation")
            try:
                with (
                    patch("app.services.generator.Anthropic", FakeAnthropic),
                    patch(
                        "app.services.generator.asyncio.to_thread",
                        new=fake_to_thread,
                    ),
                    patch("app.services.draft_store.draft_store", store),
                ):
                    response = self.client.post(
                        "/api/tasks/generation/start",
                        json={
                            "start_chapter_id": chapter_id,
                            "source_anchor_chapter_id": chapter_id,
                            "plot_direction": "连续推进当前冲突",
                            "target_word_count": 1500,
                            "mode": "chapter",
                            "draft_id": "",
                            "append_to_draft": False,
                            "reference_chapter_ids": [],
                            "pov_character": "",
                            "additional_instructions": "",
                        },
                    )
                self.assertEqual(response.status_code, 200, response.text)
                task = self.client.get(
                    f"/api/tasks/{response.json()['task_id']}"
                ).json()
                self.assertEqual(task["status"], "partial_success")
                self.assertIsNone(task["error"])
                self.assertEqual(task["total_segments"], 3)
                self.assertEqual(task["current_segment"], 1)
                self.assertGreater(task["partial_word_count"], 0)
                self.assertTrue(task["partial_text"])
                self.assertTrue(task["can_accept"])
                self.assertEqual(task["result"]["ending_status"], "partial")
                self.assertTrue(task["result"]["temp_generation"]["file_path"])
                self.assertEqual(len(calls), 2)
                for call in calls:
                    prompt_chars = len(call["system"]) + len(
                        call["messages"][0]["content"]
                    )
                    self.assertLessEqual(
                        prompt_chars,
                        settings.generation_prompt_max_chars,
                    )
                    self.assertEqual(
                        call["timeout"],
                        settings.generation_timeout_seconds,
                    )
            finally:
                settings.anthropic_api_key = original_key
                generation_router._generation_results.pop(
                    response.json()["task_id"] if 'response' in locals() else "",
                    None,
                )

    def test_segmented_generation_success_uses_one_call_per_segment(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.generator import generate_chapter

        calls: list[dict] = []
        segment_updates: list[tuple[int, int, int]] = []

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **kwargs):
            calls.append(kwargs)
            index = len(calls)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=f"第{index}段正文。" * 80,
                    )
                ]
            )

        chapter = next(iter(_corpus_store.values()))
        original_key = settings.anthropic_api_key
        settings.anthropic_api_key = "configured-for-test"
        try:
            with (
                patch("app.services.generator.Anthropic", FakeAnthropic),
                patch(
                    "app.services.generator.asyncio.to_thread",
                    new=fake_to_thread,
                ),
            ):
                content, _ = asyncio.run(
                    generate_chapter(
                        chapter=chapter,
                        kb=KnowledgeBase(
                            themes=[
                                Theme(
                                    name="测试主题",
                                    description="分段成功验收",
                                )
                            ]
                        ),
                        request=GenerationRequest(
                            start_chapter_id=chapter.chapter_id,
                            plot_direction="连续推进冲突",
                            target_word_count=1500,
                            mode="chapter",
                        ),
                        segment_callback=lambda current, total, text, _chars: (
                            segment_updates.append(
                                (current, total, len(text))
                            )
                        ),
                    )
                )
        finally:
            settings.anthropic_api_key = original_key

        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [(item[0], item[1]) for item in segment_updates],
            [(1, 3), (2, 3), (3, 3)],
        )
        self.assertIn("第1段正文", content)
        self.assertIn("第3段正文", content)
        self.assertGreater(
            segment_updates[-1][2],
            segment_updates[0][2],
        )

    def test_chapter_style_cache_reuses_unchanged_content(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.style_analyzer import analyzeChapterStyle

        calls: list[dict] = []
        constructor_kwargs: list[dict] = []
        response_json = {
            "narrative_pov": "第三人称有限视角",
            "language_style": "口语化且有画面感",
            "sentence_rhythm": "长短句交替",
            "dialogue_style": "短句交锋",
            "description_focus": "动作与心理",
            "emotional_tone": "克制的紧张感",
            "pacing": "逐步升级后留悬念",
            "character_portrayal": "通过反应和对话塑造",
            "worldbuilding_style": "随行动自然展开",
            "recurring_motifs": ["雨", "夜"],
            "taboo_or_constraints": ["避免集中说明"],
            "continuation_rules": ["保持有限视角"],
        }

        class FakeAnthropic:
            def __init__(self, *args, **kwargs):
                constructor_kwargs.append(kwargs)
                self.messages = SimpleNamespace(create=lambda **_kwargs: None)

        async def fake_to_thread(_func, *_args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text=json.dumps(response_json, ensure_ascii=False),
                    )
                ]
            )

        source = next(iter(_corpus_store.values()))
        chapter = source.model_copy(
            update={"content": source.content + ("超长章节测试" * 3000)}
        )
        original_key = settings.anthropic_api_key
        original_cache_dir = settings.style_cache_dir
        settings.anthropic_api_key = "configured-for-test"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.style_cache_dir = Path(temp_dir)
                with (
                    patch("app.services.style_analyzer.Anthropic", FakeAnthropic),
                    patch(
                        "app.services.style_analyzer.asyncio.to_thread",
                        new=fake_to_thread,
                    ),
                ):
                    first = asyncio.run(analyzeChapterStyle(chapter))
                    second = asyncio.run(analyzeChapterStyle(chapter))
        finally:
            settings.anthropic_api_key = original_key
            settings.style_cache_dir = original_cache_dir

        self.assertEqual(first.style_json.narrative_pov, "第三人称有限视角")
        self.assertEqual(second.style_json.narrative_pov, first.style_json.narrative_pov)
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(
            len(calls[0]["messages"][0]["content"]),
            settings.style_prompt_max_chars,
        )
        self.assertLessEqual(calls[0]["max_tokens"], settings.style_model_max_tokens)
        self.assertIn("[章节开头]", calls[0]["messages"][0]["content"])
        self.assertIn("[章节中段]", calls[0]["messages"][0]["content"])
        self.assertIn("[章节结尾]", calls[0]["messages"][0]["content"])
        self.assertTrue(all(item["max_retries"] == 0 for item in constructor_kwargs))

    def test_chapter_style_failure_is_skipped_with_warning(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.style_analyzer import (
            ChapterStyleAnalysisError,
            StyleAnalyzer,
            analyze_chapter_styles,
        )

        chapters = list(_corpus_store.values())[:2]
        successful = ChapterStyleCacheEntry(
            chapter_id=chapters[0].chapter_id,
            chapter_title=chapters[0].title,
            content_hash=chapters[0].content_hash,
            model_name="fake-model",
            style_json=ChapterStyleJson(
                narrative_pov="第三人称",
                language_style="简洁",
                sentence_rhythm="长短句交替",
            ),
        )
        analyzer = StyleAnalyzer(client=object())

        async def fake_analyze(chapter, **_kwargs):
            if chapter.chapter_id == chapters[0].chapter_id:
                return successful, False
            raise ChapterStyleAnalysisError("测试章节失败")

        progress_messages: list[str] = []
        original_cache_dir = settings.style_cache_dir
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                settings.style_cache_dir = Path(temp_dir)
                with patch.object(
                    analyzer,
                    "analyze_chapter_style",
                    new=fake_analyze,
                ):
                    entries, fallbacks, warnings, skipped = asyncio.run(
                        analyze_chapter_styles(
                            chapters,
                            analyzer=analyzer,
                            progress_callback=lambda _p, _s, message: (
                                progress_messages.append(message)
                            ),
                        )
                    )
        finally:
            settings.style_cache_dir = original_cache_dir

        self.assertEqual([entry.chapter_id for entry in entries], [chapters[0].chapter_id])
        self.assertEqual(skipped, [chapters[1].chapter_id])
        self.assertEqual(len(fallbacks), 1)
        self.assertTrue(warnings)
        self.assertTrue(any("继续下一章" in message for message in progress_messages))

    def test_global_style_summary_failure_keeps_local_result(self) -> None:
        from app.routers.corpus import _corpus_store
        from app.services.style_analyzer import (
            StyleAnalyzer,
            summarize_global_style,
        )

        chapter = next(iter(_corpus_store.values()))
        entry = ChapterStyleCacheEntry(
            chapter_id=chapter.chapter_id,
            chapter_title=chapter.title,
            content_hash=chapter.content_hash,
            model_name="fake-model",
            style_json=ChapterStyleJson(
                narrative_pov="第三人称有限视角",
                language_style="口语化",
                sentence_rhythm="长短句交替",
                dialogue_style="短句交锋",
                description_focus="动作与心理",
                emotional_tone="克制",
                pacing="渐进",
                character_portrayal="通过行动",
                worldbuilding_style="自然展开",
                taboo_or_constraints=["避免说明书式设定"],
                continuation_rules=["保持角色声音"],
            ),
        )
        analyzer = StyleAnalyzer(client=SimpleNamespace(
            messages=SimpleNamespace(create=lambda **_kwargs: None)
        ))
        diagnostics: dict = {}

        async def always_timeout(*_args, **_kwargs):
            raise TimeoutError("summary timeout")

        with patch(
            "app.services.style_analyzer.asyncio.to_thread",
            new=always_timeout,
        ):
            summary, error = asyncio.run(
                summarize_global_style(
                    [entry],
                    analyzer=analyzer,
                    diagnostics=diagnostics,
                )
            )

        self.assertIsNotNone(error)
        self.assertTrue(diagnostics["summary_failed"])
        self.assertEqual(summary.summary_source, "local_fallback")
        self.assertEqual(summary.analyzed_chapter_count, 1)
        self.assertTrue(summary.style_prompt_for_continuation)


if __name__ == "__main__":
    unittest.main()
