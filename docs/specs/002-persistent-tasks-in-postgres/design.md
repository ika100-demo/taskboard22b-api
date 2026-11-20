# Design — 002 Persistent tasks in Postgres

## Decisions

- Tasks live in one Postgres table `tasks` behind the existing `TaskStore` protocol: a new `PostgresTaskStore` replaces `InMemoryTaskStore` in the running app. The router and the schemas of spec 001 do not change, so the contract of spec 001 stays as it is (note "The request/response contract of spec 001 ... stays unchanged"). `InMemoryTaskStore` stays as the test double the spec 001 tests install.
- Driver: `psycopg` 3 (`psycopg[binary]`) with `psycopg_pool.ConnectionPool`, synchronous, because the endpoints are plain `def` running in FastAPI's thread pool; no ORM, three statements do not justify one. ADR: [001-postgres-task-storage](../../adr/001-postgres-task-storage.md).
- Connection string: `DATABASE_URL` from the gitops entry; when it is unset, libpq reads the injected `PG*` variables (conninfo `""`). When neither `DATABASE_URL` nor `PGHOST` is set, startup fails with `RuntimeError("DATABASE_URL or PGHOST must be set")`: there is no default credential in code (note "never a default credential in code"). A SQLAlchemy-style scheme `postgresql+<driver>://` is normalized to `postgresql://`. The URL is never logged (it carries the password).
- Schema: the service creates it itself with idempotent DDL (`CREATE TABLE IF NOT EXISTS`) inside a transaction that first takes `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, so two instances starting at once do not race (AC-002.2, AC-002.3). No migration tool yet: the first change to an existing column brings one in a later spec (ADR). The DDL runs once at startup (an unreachable database there is logged and does not stop the start) and, until it has succeeded once, again before every store operation, so a service that started while the database was down creates its schema on recovery (AC-002.6).
- Limit across instances: `add` runs in one transaction that takes `pg_advisory_xact_lock(INSERT_LOCK_KEY)`, counts, and inserts only below `MAX_TASKS`; the lock serializes inserts of every instance, so concurrent requests through two instances never pass 10,000 (AC-002.4). A count over at most 10,000 rows per insert is cheap.
- Order: a `seq` identity column, `ORDER BY seq` (note "Ordering oldest first must stay stable for equal created_at"). `created_at` is set by the database (`clock_timestamp()`) inside the insert lock, so `seq` order and `created_at` order agree even when the two pods' clocks drift (AC-002.1, AC-002.3). `id` is a Python `uuid4`, stored as `uuid`.
- Unavailability: every `psycopg.OperationalError` (connection refused, connect timeout, `QueryCanceled` from the statement timeout, `psycopg_pool.PoolTimeout`) inside the store becomes `TaskStoreUnavailableError`; the router answers `503 {"detail": "Tasks are temporarily unavailable"}`. A failed `add` rolls back, so nothing is stored (AC-002.5).
- Timeouts (system "Timeouts"): libpq `connect_timeout=2`, `options="-c statement_timeout=3000"`, `tcp_user_timeout=3000`; the pool's wait for a connection is `timeout=3.0`. A request therefore answers `503` within 6 s (AC-002.5). The pool checks a connection before handing it out (`check=ConnectionPool.check_connection`) and drops broken ones, so after an outage the next request gets a fresh connection with no restart (AC-002.6).
- `/ready` runs `SELECT 1` through the store with a 1-second budget (pool wait 1 s, `SET LOCAL statement_timeout = 1000`); `/health` never touches the database.
- App factory: `main.py` gets `create_app(database_url: str | None = None) -> FastAPI` and keeps `app = create_app()` for uvicorn. The store is built in the FastAPI lifespan (not at import), so importing `main` needs no database and two apps from `create_app(url)` are two instances against one database for tests.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard22b_api/tasks/postgres.py` | `PostgresTaskStore`, DDL, `conninfo_from_env()` | new |
| `src/taskboard22b_api/tasks/store.py` | `TaskStoreUnavailableError`; `ping()` on the protocol and on `InMemoryTaskStore` | changed |
| `src/taskboard22b_api/tasks/api.py` | maps `TaskStoreUnavailableError` to `503` on both routes | changed |
| `src/taskboard22b_api/tasks/__init__.py` | also exports `PostgresTaskStore`, `TaskStoreUnavailableError` | changed |
| `src/taskboard22b_api/main.py` | `create_app`, lifespan builds/opens/closes the store, `/ready` checks it | changed |
| `pyproject.toml`, `uv.lock` | `psycopg[binary]>=3.2`, `psycopg-pool>=3.2`; dev: `testcontainers[postgres]>=4.8` | changed |

Signatures:

```python
# store.py
class TaskStoreUnavailableError(Exception): ...   # the database cannot be used right now

class TaskStore(Protocol):
    def add(self, title: str, due_date: date | None) -> Task: ...  # raises TaskLimitReachedError, TaskStoreUnavailableError
    def list(self) -> list[Task]: ...                              # oldest first; raises TaskStoreUnavailableError
    def count(self) -> int: ...                                    # raises TaskStoreUnavailableError
    def ping(self, timeout: float = 1.0) -> bool: ...              # never raises

class InMemoryTaskStore:  # ping() -> True

# postgres.py
SCHEMA_LOCK_KEY: Final = 7_220_002_001   # constants for pg_advisory_xact_lock
INSERT_LOCK_KEY: Final = 7_220_002_002

def conninfo_from_env() -> str: ...      # DATABASE_URL (scheme normalized) or "" when PGHOST is set; else RuntimeError

class PostgresTaskStore:                 # implements TaskStore
    def __init__(self, conninfo: str, max_tasks: int = MAX_TASKS) -> None: ...
        # ConnectionPool(conninfo, open=False, min_size=1, max_size=10, timeout=3.0,
        #                check=ConnectionPool.check_connection,
        #                kwargs={"connect_timeout": 2, "tcp_user_timeout": 3000,
        #                        "options": "-c statement_timeout=3000"})
    def open(self) -> None: ...          # pool.open(wait=False), then try ensure_schema(); log and continue if unavailable
    def close(self) -> None: ...         # pool.close()
    def ensure_schema(self) -> None: ... # once per process (flag under a threading.Lock); raises TaskStoreUnavailableError
    # add():  ensure_schema; BEGIN; advisory lock; SELECT count(*); >= max -> rollback, TaskLimitReachedError;
    #         INSERT ... VALUES (%s, %s, %s, clock_timestamp()) RETURNING id, title, due_date, created_at; COMMIT
    # list(): ensure_schema; SELECT id, title, due_date, created_at FROM tasks ORDER BY seq
    # ping(): pool.connection(timeout=timeout); SET LOCAL statement_timeout = <timeout ms>; SELECT 1 -> True; any error -> False

# main.py
def create_app(database_url: str | None = None) -> FastAPI: ...
    # lifespan: conninfo = database_url if given else conninfo_from_env()
    #           store = PostgresTaskStore(conninfo); store.open(); app.state.task_store = store; yield; store.close()
app = create_app()
```

`/ready` takes the store through `Depends(get_task_store)`, so a test override (`InMemoryTaskStore`) answers `200`.

Logging (structlog): `database_unavailable` at warning with `operation` and `error` (exception class name only), `schema_ensured` at info once; never the URL, never a title.

## Contract

Unchanged from spec 001's design (task object, `422` body, `201`, `507`, oldest-first order, unknown fields ignored, no authentication); added:

**`GET /tasks`**

| Status | When | Body |
|---|---|---|
| `200` | database reachable | JSON array of task objects, oldest first, unpaged; `[]` when none (AC-002.1, AC-002.2, AC-002.3) |
| `503` | database unreachable or the query did not finish in time | `{"detail": "Tasks are temporarily unavailable"}` (AC-002.5) |

**`POST /tasks`**

| Status | When | Body |
|---|---|---|
| `201` | valid input, fewer than 10,000 tasks stored | the task object |
| `422` | invalid `title` or `due_date` (unchanged; validated before the database is touched, so it answers `422` even when the database is down) | FastAPI standard validation body |
| `503` | database unreachable or the statement did not finish in time; nothing stored | `{"detail": "Tasks are temporarily unavailable"}` (AC-002.5) |
| `507` | 10,000 tasks already stored, also under concurrent requests through several instances; nothing stored | `{"detail": "Task limit of 10000 reached"}` (AC-002.4) |

`503` answers arrive within 6 seconds of the request.

**`GET /ready`**: `200 {"status": "ready"}` when `SELECT 1` succeeds within 1 s; `503 {"status": "not ready"}` otherwise (AC-002.5, AC-002.6). **`GET /health`**: always `200 {"status": "ok"}`. `/ping` and `/metrics` unchanged.

## Data

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         UUID        NOT NULL UNIQUE,
    title      TEXT        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   DATE,
    created_at TIMESTAMPTZ NOT NULL
);
```

Created by the service (AC-002.2); at most `MAX_TASKS` rows. `created_at` round-trips with microsecond precision, so a task reads back with the exact `created_at` it was created with (AC-002.1).

## Test seam (for testers)

- **Database:** a session fixture in `tests/conftest.py` yields a server URL: `TEST_DATABASE_URL` when set, else a `testcontainers.postgres.PostgresContainer("postgres:17-alpine")` (import inside the fixture, so the rest of the suite runs without Docker or the package). A function fixture creates a fresh database `t_<uuid hex>` on that server per test and drops it afterwards: AC-002.2's "empty database without the service's tables" is that fresh database.
- **Instances and restarts:** `with TestClient(create_app(database_url=url)) as c:` runs the lifespan (a plain `TestClient(app)` does not). Two such clients on one URL are two instances (AC-002.3, AC-002.4); leaving the `with` block and opening a new client on the same URL is a restart (AC-002.1).
- **Unreachable and back:** put a small TCP forwarder (test code, a thread with `cut()` closing the listener and every forwarded socket, `restore()` listening again on the same port with `SO_REUSEADDR`) between the app and the database and give the app the forwarder's URL (AC-002.5, AC-002.6). Recovery: poll `GET /ready` for up to 15 s after `restore()`.
- **10,000 tasks:** fill the table directly, e.g. `INSERT INTO tasks (id, title, created_at) SELECT gen_random_uuid(), 't' || g, clock_timestamp() FROM generate_series(1, 10000) g` after the app has created the schema (AC-002.4).
- `tests/test_tasks_acceptance.py::test_restart_yields_empty_list` tests the superseded AC-001.6 and should be removed with the 002 acceptance tests; the other spec 001 tests keep working through the `InMemoryTaskStore` override.

## Smoke

Read-only (every environment): `GET /ready` answers `200 {"status": "ready"}` and `GET /tasks` answers `200` with an array, which proves the deployed instance reaches its database. Writing (dev only, `@pytest.mark.writes`): a created `smoke-<uuid>` task appears in repeated `GET /tasks` calls with the same `id` and `created_at` (requests land on both replicas through the Service; AC-002.3).
