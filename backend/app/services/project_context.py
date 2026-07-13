from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any, Generic, TypeVar

from app.config import settings


_current_project_id: ContextVar[str] = ContextVar(
    "noval_current_project_id",
    default=settings.project_id,
)


def get_current_project_id() -> str:
    return _current_project_id.get()


@contextmanager
def use_project(project_id: str) -> Iterator[None]:
    token = _current_project_id.set(project_id)
    try:
        yield
    finally:
        _current_project_id.reset(token)


async def run_in_project(
    project_id: str,
    operation: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    with use_project(project_id):
        result = operation(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result


T = TypeVar("T")


class ProjectScopedStore(Generic[T]):
    def __init__(
        self,
        legacy_store: T,
        factory: Callable[[str], T],
    ) -> None:
        self._legacy_store = legacy_store
        self._factory = factory
        self._stores: dict[str, T] = {}
        self._lock = RLock()

    def for_project(self, project_id: str) -> T:
        if project_id == settings.project_id:
            return self._legacy_store
        with self._lock:
            if project_id not in self._stores:
                self._stores[project_id] = self._factory(project_id)
            return self._stores[project_id]

    def current(self) -> T:
        return self.for_project(get_current_project_id())

    def clear(self, project_id: str | None = None) -> None:
        with self._lock:
            if project_id is None:
                self._stores.clear()
            else:
                self._stores.pop(project_id, None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.current(), name)


V = TypeVar("V")


class ProjectScopedDict(MutableMapping[str, V]):
    def __init__(self, legacy: dict[str, V] | None = None) -> None:
        self._legacy = legacy if legacy is not None else {}
        self._values: dict[str, dict[str, V]] = {}
        self._lock = RLock()

    def for_project(self, project_id: str) -> dict[str, V]:
        if project_id == settings.project_id:
            return self._legacy
        with self._lock:
            return self._values.setdefault(project_id, {})

    def current(self) -> dict[str, V]:
        return self.for_project(get_current_project_id())

    def clear_project(self, project_id: str) -> None:
        with self._lock:
            if project_id == settings.project_id:
                self._legacy.clear()
            else:
                self._values.pop(project_id, None)

    def reset_non_legacy(self) -> None:
        with self._lock:
            self._values.clear()

    def __getitem__(self, key: str) -> V:
        return self.current()[key]

    def __setitem__(self, key: str, value: V) -> None:
        self.current()[key] = value

    def __delitem__(self, key: str) -> None:
        del self.current()[key]

    def __iter__(self):
        return iter(self.current())

    def __len__(self) -> int:
        return len(self.current())
