from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import settings
from app.services.file_ops import atomic_write_json, read_json_with_recovery
from app.models.schemas import (
    BookPlan,
    BookPlanUpdate,
    ChapterPlan,
    ChapterPlanInput,
    ProjectOutline,
    ProjectOutlineUpdate,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlanningStore:
    def __init__(
        self,
        root: Path | None = None,
        *,
        project_id: str = "longzu_continuation",
        title: str = "本地续写项目",
    ) -> None:
        self.project_id = project_id
        self.project_title = title
        self._lock = RLock()
        self.set_root(Path(root or settings.continuation_project_dir))

    def set_root(self, root: Path) -> None:
        with self._lock:
            self.root = Path(root)
            self.outline_path = self.root / "outline.json"
            self.plans_path = self.root / "chapter_plans.json"
            self.book_plan_path = self.root / "book_plan.json"
            self._ensure_files()

    def _ensure_files(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.outline_path.exists():
            self._write_json(
                self.outline_path,
                ProjectOutline(
                    project_id=self.project_id,
                    title=self.project_title,
                ).model_dump(mode="json"),
            )
        if not self.plans_path.exists():
            self._write_json(self.plans_path, [])

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        atomic_write_json(path, value)

    @staticmethod
    def _validate_id(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("规划 ID 格式不安全")
        return value

    def get_outline(self) -> ProjectOutline:
        with self._lock:
            self._ensure_files()
            try:
                return ProjectOutline.model_validate(
                    read_json_with_recovery(self.outline_path)
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"项目总纲无法读取: {exc}") from exc

    def save_outline(self, value: ProjectOutlineUpdate) -> ProjectOutline:
        with self._lock:
            outline = ProjectOutline(
                **value.model_dump(),
                project_id=self.project_id,
                updated_at=_now(),
            )
            self._write_json(
                self.outline_path,
                outline.model_dump(mode="json"),
            )
            return outline

    def _read_plans(self) -> list[dict[str, Any]]:
        self._ensure_files()
        try:
            value = read_json_with_recovery(self.plans_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"章节规划无法读取: {exc}") from exc
        return value if isinstance(value, list) else []

    def list_plans(self) -> list[ChapterPlan]:
        with self._lock:
            plans = [ChapterPlan.model_validate(item) for item in self._read_plans()]
            return sorted(plans, key=lambda item: (item.order, item.updated_at))

    def get_plan(self, plan_id: str) -> ChapterPlan:
        safe_id = self._validate_id(plan_id)
        with self._lock:
            for item in self._read_plans():
                if item.get("plan_id") == safe_id:
                    return ChapterPlan.model_validate(item)
        raise KeyError(plan_id)

    def create_plan(self, value: ChapterPlanInput) -> ChapterPlan:
        with self._lock:
            plans = self._read_plans()
            numbers = []
            for item in plans:
                match = re.fullmatch(r"plan_(\d+)", str(item.get("plan_id", "")))
                if match:
                    numbers.append(int(match.group(1)))
            plan = ChapterPlan(
                plan_id=f"plan_{max(numbers, default=0) + 1:03d}",
                **value.model_dump(),
                updated_at=_now(),
            )
            plans.append(plan.model_dump(mode="json"))
            self._write_json(self.plans_path, plans)
            return plan

    def update_plan(self, plan_id: str, value: ChapterPlanInput) -> ChapterPlan:
        safe_id = self._validate_id(plan_id)
        with self._lock:
            plans = self._read_plans()
            for index, item in enumerate(plans):
                if item.get("plan_id") == safe_id:
                    plan = ChapterPlan(
                        plan_id=safe_id,
                        **value.model_dump(),
                        updated_at=_now(),
                    )
                    plans[index] = plan.model_dump(mode="json")
                    self._write_json(self.plans_path, plans)
                    return plan
        raise KeyError(plan_id)

    def delete_plan(self, plan_id: str) -> bool:
        safe_id = self._validate_id(plan_id)
        with self._lock:
            plans = self._read_plans()
            remaining = [item for item in plans if item.get("plan_id") != safe_id]
            if len(remaining) == len(plans):
                return False
            self._write_json(self.plans_path, remaining)
            return True

    def get_book_plan(self) -> BookPlan | None:
        with self._lock:
            if not self.book_plan_path.exists():
                return None
            try:
                return BookPlan.model_validate(
                    read_json_with_recovery(self.book_plan_path)
                )
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"全书规划无法读取: {exc}") from exc

    def save_book_plan(self, value: BookPlan) -> BookPlan:
        with self._lock:
            current = self.get_book_plan()
            now = _now()
            saved = value.model_copy(
                update={
                    "project_id": self.project_id,
                    "created_at": current.created_at if current else value.created_at,
                    "updated_at": now,
                    "target_chapter_count": len(value.chapters),
                }
            )
            self._write_json(
                self.book_plan_path,
                saved.model_dump(mode="json"),
            )
            return saved

    def update_book_plan(self, value: BookPlanUpdate) -> BookPlan:
        current = self.get_book_plan()
        saved = BookPlan(
            **value.model_dump(),
            book_plan_id=current.book_plan_id if current else "book_plan_main",
            project_id=self.project_id,
            model_name=current.model_name if current else "",
            prompt_chars=current.prompt_chars if current else 0,
            generation_source=current.generation_source if current else "manual",
            created_at=current.created_at if current else _now(),
            updated_at=_now(),
        )
        return self.save_book_plan(saved)

    def sync_outline_from_book_plan(self, book_plan: BookPlan) -> ProjectOutline:
        return self.save_outline(
            ProjectOutlineUpdate(
                title=book_plan.title,
                premise=book_plan.premise,
                main_conflict=book_plan.main_conflict,
                tone=book_plan.tone,
                ending_direction=book_plan.ending_direction,
                continuity_notes=book_plan.continuity_notes,
                foreshadowing=book_plan.foreshadowing,
                character_arcs=book_plan.character_arcs,
                prohibitions=book_plan.prohibitions,
            )
        )

    def apply_book_plan(self, book_plan: BookPlan, draft_store) -> list[ChapterPlan]:
        with self._lock:
            raw_plans = self._read_plans()
            manual_plans = [
                item
                for item in raw_plans
                if item.get("book_plan_id") != book_plan.book_plan_id
            ]
            existing = {
                int(item.get("order", 0)): item
                for item in raw_plans
                if item.get("book_plan_id") == book_plan.book_plan_id
            }
            plan_numbers = []
            for item in raw_plans:
                match = re.fullmatch(r"plan_(\d+)", str(item.get("plan_id", "")))
                if match:
                    plan_numbers.append(int(match.group(1)))
            next_plan_number = max(plan_numbers, default=0) + 1
            applied: list[ChapterPlan] = []
            for chapter in sorted(book_plan.chapters, key=lambda item: item.order):
                previous = existing.get(chapter.order, {})
                draft_id = str(previous.get("draft_id", ""))
                if draft_id:
                    try:
                        draft_store.get_draft(draft_id)
                    except KeyError:
                        draft_id = ""
                if not draft_id:
                    draft = draft_store.create_draft(
                        title=chapter.title,
                        source_anchor_chapter_id=book_plan.source_anchor_chapter_id,
                        notes=f"自动构想来源：{book_plan.book_plan_id}",
                    )
                    draft_id = draft.draft_id
                plan_id = str(previous.get("plan_id", ""))
                if not plan_id:
                    plan_id = f"plan_{next_plan_number:03d}"
                    next_plan_number += 1
                plan = ChapterPlan(
                    plan_id=plan_id,
                    draft_id=draft_id,
                    book_plan_id=book_plan.book_plan_id,
                    title=chapter.title,
                    order=chapter.order,
                    anchor_chapter_id=book_plan.source_anchor_chapter_id,
                    target_words=chapter.target_words,
                    chapter_summary=chapter.chapter_summary,
                    chapter_goal=chapter.chapter_goal,
                    opening_state=chapter.opening_state,
                    ending_state=chapter.ending_state,
                    previous_bridge=chapter.previous_bridge,
                    next_bridge=chapter.next_bridge,
                    plot_beats=chapter.plot_beats,
                    chapter_function=chapter.chapter_function,
                    characters=chapter.characters,
                    conflict=chapter.conflict,
                    foreshadowing_to_plant=chapter.foreshadowing_to_plant,
                    foreshadowing_to_resolve=chapter.foreshadowing_to_resolve,
                    emotional_tone=chapter.emotional_tone,
                    word_count_reason=chapter.word_count_reason,
                    ending_hook=chapter.ending_hook,
                    status=str(previous.get("status", "planned")),
                    updated_at=_now(),
                )
                applied.append(plan)
            self._write_json(
                self.plans_path,
                manual_plans + [item.model_dump(mode="json") for item in applied],
            )
            return sorted(
                [ChapterPlan.model_validate(item) for item in manual_plans] + applied,
                key=lambda item: (item.order, item.updated_at),
            )

    def update_plan_status(self, plan_id: str, status: str) -> ChapterPlan:
        current = self.get_plan(plan_id)
        return self.update_plan(
            plan_id,
            ChapterPlanInput(
                **current.model_dump(
                    exclude={"plan_id", "updated_at", "status"}
                ),
                status=status,
            ),
        )

    def previous_draft_id(self, plan_id: str) -> str:
        current = self.get_plan(plan_id)
        previous = [
            plan
            for plan in self.list_plans()
            if plan.order < current.order and plan.draft_id
        ]
        return previous[-1].draft_id if previous else ""

    def compact_context(self, plan_id: str = "") -> str:
        outline = self.get_outline()
        sections = []
        outline_lines = [
            f"续写总目标：{outline.premise[:800]}",
            f"主线冲突：{outline.main_conflict[:600]}",
            f"整体基调：{outline.tone[:300]}",
            f"结局方向：{outline.ending_direction[:500]}",
        ]
        if outline.character_arcs:
            outline_lines.append(
                "人物走向：" + "；".join(outline.character_arcs[:6])
            )
        if outline.foreshadowing:
            outline_lines.append(
                "已有伏笔：" + "；".join(outline.foreshadowing[:8])
            )
        if outline.continuity_notes:
            outline_lines.append(
                "连续性要求：" + "；".join(outline.continuity_notes[:6])
            )
        if outline.prohibitions:
            outline_lines.append(
                "禁止事项：" + "；".join(outline.prohibitions[:6])
            )
        sections.append("## 项目总纲摘要\n" + "\n".join(outline_lines))
        if plan_id:
            plan = self.get_plan(plan_id)
            plan_lines = [
                f"章节标题：{plan.title}",
                f"本章摘要：{plan.chapter_summary[:1000]}",
                f"本章目标：{plan.chapter_goal[:800]}",
                f"开头状态：{plan.opening_state[:700]}",
                f"结尾状态：{plan.ending_state[:700]}",
                f"承接上一章：{plan.previous_bridge[:600]}",
                f"引出下一章：{plan.next_bridge[:600]}",
                f"本章冲突：{plan.conflict[:600]}",
                "情节点：" + "；".join(plan.plot_beats[:8]),
                "章节功能：" + "；".join(plan.chapter_function[:6]),
                "参与角色：" + "、".join(plan.characters[:10]),
                "需要埋下：" + "；".join(plan.foreshadowing_to_plant[:6]),
                "需要回收：" + "；".join(plan.foreshadowing_to_resolve[:6]),
                f"情绪节奏：{plan.emotional_tone[:400]}",
                f"建议字数：{plan.target_words}；原因：{plan.word_count_reason[:400]}",
                f"章末钩子：{plan.ending_hook[:500]}",
            ]
            next_plan = next(
                (
                    item
                    for item in self.list_plans()
                    if item.book_plan_id == plan.book_plan_id
                    and item.order == plan.order + 1
                ),
                None,
            )
            if next_plan:
                plan_lines.append(
                    f"下一章规划摘要：{next_plan.title}；"
                    f"{(next_plan.chapter_summary or next_plan.chapter_goal)[:700]}"
                )
            sections.append("## 当前章节规划\n" + "\n".join(plan_lines))
        return "\n\n".join(sections)


from app.services.project_context import ProjectScopedStore
from app.services.project_store import project_store


def _project_planning_store(project_id: str) -> PlanningStore:
    project = project_store.get(project_id)
    return PlanningStore(
        project_store.layout(project_id).planning,
        project_id=project_id,
        title=project.title,
    )


planning_store = ProjectScopedStore(PlanningStore(), _project_planning_store)
