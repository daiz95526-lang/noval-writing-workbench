from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.project_context import get_current_project_id
from app.services.project_store import project_store


@dataclass(frozen=True)
class RuntimeProjectPaths:
    project_id: str
    source: Path
    processed: Path
    index: Path
    reports: Path
    analysis_style: Path
    analysis_knowledge: Path
    planning: Path
    draft_store: Path
    writing: Path
    exports: Path
    legacy: bool


def get_project_paths(project_id: str | None = None) -> RuntimeProjectPaths:
    selected = project_id or get_current_project_id()
    project = project_store.get(selected)
    if project.storage_mode == "legacy":
        legacy = project_store.legacy_layout()
        return RuntimeProjectPaths(
            project_id=selected,
            source=legacy["source"],
            processed=legacy["processed"],
            index=legacy["index"],
            reports=legacy["reports"],
            analysis_style=legacy["style"],
            analysis_knowledge=legacy["analysis"],
            planning=legacy["planning"],
            draft_store=legacy["planning"],
            writing=legacy["writing"],
            exports=legacy["writing"] / "exports",
            legacy=True,
        )
    layout = project_store.layout(selected)
    source = layout.corpus_source
    if project.corpus_config.mode == "external_readonly":
        corpus_config = project_store.validate_corpus_config(project.corpus_config)
        configured = [
            Path(value).expanduser().resolve()
            for value in corpus_config.source_paths
            if value.strip()
        ]
        if configured:
            source = configured[0]
    return RuntimeProjectPaths(
        project_id=selected,
        source=source,
        processed=layout.corpus_processed,
        index=layout.corpus_index / "chapters_meta.json",
        reports=layout.corpus_reports,
        analysis_style=layout.analysis_style,
        analysis_knowledge=layout.analysis_knowledge,
        planning=layout.planning,
        draft_store=layout.draft_store,
        writing=layout.writing,
        exports=layout.exports,
        legacy=False,
    )
