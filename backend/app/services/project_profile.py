from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.project_context import get_current_project_id
from app.services.project_store import project_store


@dataclass(frozen=True)
class ProjectRuntimeProfile:
    project_id: str
    title: str
    legacy: bool

    def adapt_legacy_prompt(self, value: str) -> str:
        if self.legacy:
            return value
        replacements = (
            (
                "你是江南，中国著名幻想小说作家，《龙族》系列的作者。",
                "你是一位擅长长篇小说创作与连续性维护的写作助手。",
            ),
            ("龙族 I-V", "既有各卷"),
            ("龙族 VI：未命名续写", "未命名全书规划"),
            ("《龙族》", f"《{self.title}》"),
            ("龙族III", "作品相关卷册"),
            ("龙族", "作品"),
        )
        adapted = value
        for source, target in replacements:
            adapted = adapted.replace(source, target)
        return adapted


def get_project_profile() -> ProjectRuntimeProfile:
    project_id = get_current_project_id()
    try:
        project = project_store.get(project_id)
    except (KeyError, RuntimeError, ValueError):
        return ProjectRuntimeProfile(
            project_id=project_id,
            title=settings.project_title,
            legacy=project_id == settings.project_id,
        )
    return ProjectRuntimeProfile(
        project_id=project.project_id,
        title=project.title,
        legacy=project.storage_mode == "legacy",
    )
