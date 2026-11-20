---
spec_id: 002-persistent-tasks-in-postgres
shape: service-python
spec_hash: 3afbc5a6dd74
summary: Store tasks in Postgres behind the TaskStore protocol, with 503 on database outages and a database-backed /ready
tasks:
  - id: t1
    title: Add the Postgres task store (psycopg pool, self-created schema, cross-instance limit)
    files: [pyproject.toml, uv.lock, src/taskboard22b_api/tasks/postgres.py, src/taskboard22b_api/tasks/store.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Wire the Postgres store into the app (create_app, lifespan, 503 mapping, database-backed /ready)
    files: [src/taskboard22b_api/tasks/api.py, src/taskboard22b_api/tasks/__init__.py, src/taskboard22b_api/main.py, tests/test_health.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: true
    depends_on: [t1]
---

# Plan — 002 Persistent tasks in Postgres

See [design.md](design.md) for the binding contract, the signatures, the table and the test seam. No gitops task: the system plan already wires `DATABASE_URL`/`PG*` and 2 replicas in dev, and `/ready` and `/health` keep their paths.

## t1 — Add the Postgres task store (psycopg pool, self-created schema, cross-instance limit)

**Files:** pyproject.toml, uv.lock, src/taskboard22b_api/tasks/postgres.py, src/taskboard22b_api/tasks/store.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** A `PostgresTaskStore` implementing the `TaskStore` protocol that keeps tasks in one shared table, creates its schema itself, holds the 10,000 limit across instances and turns every database outage into `TaskStoreUnavailableError`. The app does not use it yet, so the existing suite stays green.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` and `psycopg-pool>=3.2` to `dependencies`, `testcontainers[postgres]>=4.8` to the `dev` extra; regenerate `uv.lock` through the devbox environment (never `uv add`/`pip` directly).
- `store.py`: add `TaskStoreUnavailableError`, add `ping(self, timeout: float = 1.0) -> bool` to the protocol, `InMemoryTaskStore.ping` returns `True`.
- `postgres.py`: `conninfo_from_env()` per design (normalize `postgresql+<driver>://`, `""` when only `PGHOST` is set, `RuntimeError` when neither); never log the URL.
- `PostgresTaskStore.__init__`: the `ConnectionPool` exactly as in design (`open=False`, `timeout=3.0`, `check=ConnectionPool.check_connection`, `connect_timeout=2`, `tcp_user_timeout=3000`, `statement_timeout=3000`); `open()` = `pool.open(wait=False)` plus a best-effort `ensure_schema()`; `close()` closes the pool.
- `ensure_schema()`: DDL from design's Data section in one transaction after `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`; a process flag guarded by a `threading.Lock` makes it run until it has succeeded once; called first in `add`, `list`, `count`.
- `add()`: one transaction: `pg_advisory_xact_lock(INSERT_LOCK_KEY)`, `SELECT count(*)`, `TaskLimitReachedError` at `>= max_tasks` (rolled back), else `INSERT ... clock_timestamp() RETURNING ...`; return `Task(id=str(row.id), ...)`.
- `list()`: `ORDER BY seq`; `count()`: `SELECT count(*)`.
- Catch `psycopg.OperationalError` (covers `PoolTimeout`, `QueryCanceled`) around every operation, log `database_unavailable` (operation, exception class), raise `TaskStoreUnavailableError` from it; `ping()` returns `False` on any exception and bounds itself to `timeout` (pool wait and `SET LOCAL statement_timeout`).
- mypy strict-clean; `bandit` clean (parameterized queries only, no string-built SQL with values).

**Done when:** `devbox run ci` is green; the acceptance tests pass only after t2.

## t2 — Wire the Postgres store into the app (create_app, lifespan, 503 mapping, database-backed /ready)

**Files:** src/taskboard22b_api/tasks/api.py, src/taskboard22b_api/tasks/__init__.py, src/taskboard22b_api/main.py, tests/test_health.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** The running service stores tasks in Postgres, answers `503` while the database is unreachable, reports readiness from the database and recovers without a restart, through the contract in design.md.

**Implementation notes:**
- `main.py`: `create_app(database_url: str | None = None) -> FastAPI` with a lifespan that builds `PostgresTaskStore(database_url or conninfo_from_env())`, calls `open()`, sets `app.state.task_store`, and calls `close()` on shutdown; `app = create_app()` stays the uvicorn target; routes, metrics middleware and tracing move into the factory unchanged; `InMemoryTaskStore` is no longer created there.
- `main.py`: `/ready` takes the store via `Depends(get_task_store)`: `store.ping(1.0)` true -> `200 {"status": "ready"}`, else `JSONResponse(503, {"status": "not ready"})`; `/health` untouched.
- `api.py`: both routes catch `TaskStoreUnavailableError` and raise `HTTPException(503, "Tasks are temporarily unavailable")`; the `507` path unchanged; validation stays before any store call.
- `__init__.py`: export `PostgresTaskStore`, `TaskStoreUnavailableError` next to the existing names.
- `tests/test_health.py`: the `/ready` test installs `InMemoryTaskStore` through `app.dependency_overrides[get_task_store]` (and removes it), because `/ready` now depends on the store.
- `docs/env-vars.md`: a `Database` section: `DATABASE_URL` (no default; set by the gitops entry), the `PG*` fallback, and the fixed timeouts.

**Done when:** the acceptance tests for AC-002.1 to AC-002.6 pass against the test Postgres (design's test seam), the spec 001 acceptance tests still pass, and `devbox run ci` is green.
