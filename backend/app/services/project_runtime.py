from __future__ import annotations


def clear_project_runtime(project_id: str) -> None:
    from app.routers.analysis import _style_profiles, _tasks
    from app.routers.corpus import _corpus_store, _loaded_projects
    from app.routers.generation import _generation_results, _knowledge_bases
    from app.services.draft_store import draft_store
    from app.services.planning_store import planning_store
    from app.services.task_manager import task_manager
    from app.services.writing_project_store import writing_project_store

    _corpus_store.clear_project(project_id)
    _loaded_projects.discard(project_id)
    _style_profiles.clear_project(project_id)
    _tasks.clear_project(project_id)
    _generation_results.clear_project(project_id)
    _knowledge_bases.clear_project(project_id)
    draft_store.clear(project_id)
    planning_store.clear(project_id)
    writing_project_store.clear(project_id)
    task_manager.clear(project_id)
