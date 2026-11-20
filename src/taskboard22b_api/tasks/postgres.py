"""Postgres task store: one shared table, self-created schema, limit held across instances."""

from __future__ import annotations

import builtins
import os
import threading
from datetime import date
from typing import Final
from uuid import UUID, uuid4

import psycopg
import structlog
from psycopg_pool import ConnectionPool

from .models import Task
from .store import MAX_TASKS, TaskLimitReachedError, TaskStoreUnavailableError

SCHEMA_LOCK_KEY: Final = 7_220_002_001
INSERT_LOCK_KEY: Final = 7_220_002_002

_DDL: Final = """
CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID        NOT NULL UNIQUE,
    title      TEXT        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   DATE,
    created_at TIMESTAMPTZ NOT NULL
)
"""

_log = structlog.get_logger(__name__)


def conninfo_from_env() -> str:
    """Connection string from DATABASE_URL, or "" so libpq reads the PG* variables."""
    url = os.environ.get("DATABASE_URL")
    if url:
        scheme, sep, rest = url.partition("://")
        if sep and scheme.startswith("postgresql+"):
            return f"postgresql://{rest}"
        return url
    if os.environ.get("PGHOST"):
        return ""
    raise RuntimeError("DATABASE_URL or PGHOST must be set")


class PostgresTaskStore:
    """TaskStore backed by Postgres; every database outage becomes TaskStoreUnavailableError."""

    def __init__(self, conninfo: str, max_tasks: int = MAX_TASKS) -> None:
        self._max_tasks = max_tasks
        self._pool = ConnectionPool(
            conninfo,
            open=False,
            min_size=1,
            max_size=10,
            timeout=3.0,
            check=ConnectionPool.check_connection,
            kwargs={
                "connect_timeout": 2,
                "tcp_user_timeout": 3000,
                "options": "-c statement_timeout=3000",
            },
        )
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def open(self) -> None:
        self._pool.open(wait=False)
        try:
            self.ensure_schema()
        except TaskStoreUnavailableError:
            pass  # already logged; the schema is created on the first operation after recovery

    def close(self) -> None:
        self._pool.close()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            try:
                with self._pool.connection() as conn:
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
                    conn.execute(_DDL)
            except psycopg.OperationalError as exc:
                raise self._unavailable("ensure_schema", exc) from exc
            self._schema_ready = True
            _log.info("schema_ensured")

    def add(self, title: str, due_date: date | None) -> Task:
        self.ensure_schema()
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (INSERT_LOCK_KEY,))
                row = conn.execute("SELECT count(*) FROM tasks").fetchone()
                if row is not None and row[0] >= self._max_tasks:
                    raise TaskLimitReachedError
                inserted = conn.execute(
                    "INSERT INTO tasks (id, title, due_date, created_at) "
                    "VALUES (%s, %s, %s, clock_timestamp()) "
                    "RETURNING id, title, due_date, created_at",
                    (uuid4(), title, due_date),
                ).fetchone()
        except psycopg.OperationalError as exc:
            raise self._unavailable("add", exc) from exc
        assert inserted is not None
        return _to_task(inserted)

    def list(self) -> builtins.list[Task]:
        self.ensure_schema()
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    "SELECT id, title, due_date, created_at FROM tasks ORDER BY seq"
                ).fetchall()
        except psycopg.OperationalError as exc:
            raise self._unavailable("list", exc) from exc
        return [_to_task(row) for row in rows]

    def count(self) -> int:
        self.ensure_schema()
        try:
            with self._pool.connection() as conn:
                row = conn.execute("SELECT count(*) FROM tasks").fetchone()
        except psycopg.OperationalError as exc:
            raise self._unavailable("count", exc) from exc
        return int(row[0]) if row is not None else 0

    def ping(self, timeout: float = 1.0) -> bool:
        try:
            with self._pool.connection(timeout=timeout) as conn:
                conn.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (str(max(1, int(timeout * 1000))),),
                )
                conn.execute("SELECT 1")
        except Exception:
            return False
        return True

    @staticmethod
    def _unavailable(operation: str, exc: Exception) -> TaskStoreUnavailableError:
        _log.warning("database_unavailable", operation=operation, error=type(exc).__name__)
        return TaskStoreUnavailableError("database unavailable")


def _to_task(row: tuple[UUID, str, date | None, object]) -> Task:
    task_id, title, due_date, created_at = row
    return Task.model_validate(
        {"id": str(task_id), "title": title, "due_date": due_date, "created_at": created_at}
    )
