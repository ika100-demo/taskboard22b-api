"""Task storage: protocol and the in-memory implementation."""

from __future__ import annotations

import builtins
import threading
from datetime import UTC, date, datetime
from typing import Final, Protocol
from uuid import uuid4

from .models import Task

MAX_TASKS: Final = 10_000


class TaskLimitReachedError(Exception):
    """Raised when the store already holds the maximum number of tasks."""


class TaskStoreUnavailableError(Exception):
    """Raised when the database cannot be used right now."""


class TaskStore(Protocol):
    def add(self, title: str, due_date: date | None) -> Task: ...

    def list(self) -> builtins.list[Task]: ...

    def count(self) -> int: ...

    def ping(self, timeout: float = 1.0) -> bool: ...


class InMemoryTaskStore:
    """Process-local store; lost on restart."""

    def __init__(self, max_tasks: int = MAX_TASKS) -> None:
        self._max_tasks = max_tasks
        self._tasks: builtins.list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: date | None) -> Task:
        with self._lock:
            if len(self._tasks) >= self._max_tasks:
                raise TaskLimitReachedError
            task = Task(
                id=str(uuid4()),
                title=title,
                due_date=due_date,
                created_at=datetime.now(UTC),
            )
            self._tasks.append(task)
            return task

    def list(self) -> builtins.list[Task]:
        with self._lock:
            return self._tasks.copy()

    def count(self) -> int:
        with self._lock:
            return len(self._tasks)

    def ping(self, timeout: float = 1.0) -> bool:
        return True
