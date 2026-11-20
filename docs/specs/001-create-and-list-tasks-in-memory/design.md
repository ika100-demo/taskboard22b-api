# Design — 001 Create and list tasks in memory

## Decisions

- One package `taskboard22b_api/tasks/` holds the feature: Pydantic schemas (the contract), a `TaskStore` protocol with one `InMemoryTaskStore` implementation, and a FastAPI `APIRouter`. The route depends on the protocol only, through the dependency `get_task_store`, so that a later persistent store replaces the in-memory one without touching the contract (note "keep the task contract independent of how tasks are held").
- The store lives in process memory, created once at import of `main.py` and held on `app.state.task_store`; a restart starts empty (AC-001.6). No env var, no gitops change: the 10,000 limit is a constant `MAX_TASKS = 10_000` (A7, AC-001.7), because the spec fixes it.
- Endpoints are plain `def` (FastAPI runs them in a thread pool), so the store guards "check count, then append" with a `threading.Lock`; the limit then holds under concurrent requests.
- `due_date` is validated by a `mode="before"` validator, not by Pydantic's lax `date` parsing, because lax parsing also accepts integers (Unix timestamps) and midnight datetime strings such as `"2026-12-24T00:00:00"`, which AC-001.5 rejects.
- `title` uses `StringConstraints(strip_whitespace=True, min_length=1, max_length=200)` on `str`; Pydantic v2 does not coerce numbers to `str`, so non-strings fail (AC-001.4, A1).
- List order is insertion order of the store, not a sort on `created_at`, so that two tasks with an equal timestamp still list in creation order (AC-001.3, A4).
- No ADR: the store protocol is feature-local until persistence is chosen; that later spec decides the technology and its ADR.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard22b_api/tasks/__init__.py` | exports `router`, `get_task_store`, `InMemoryTaskStore` | new |
| `src/taskboard22b_api/tasks/models.py` | `TaskCreate` (request), `Task` (response) schemas, `due_date` validator | new |
| `src/taskboard22b_api/tasks/store.py` | `TaskStore` protocol, `InMemoryTaskStore`, `TaskLimitReachedError`, `MAX_TASKS` | new |
| `src/taskboard22b_api/tasks/api.py` | `APIRouter` with `POST /tasks`, `GET /tasks`; `get_task_store` dependency | new |
| `src/taskboard22b_api/main.py` | creates the store on `app.state.task_store`, includes the router | changed |

Signatures:

```python
MAX_TASKS: Final = 10_000

class TaskLimitReachedError(Exception): ...

class TaskStore(Protocol):
    def add(self, title: str, due_date: date | None) -> Task: ...   # raises TaskLimitReachedError
    def list(self) -> list[Task]: ...                                # oldest first
    def count(self) -> int: ...

class InMemoryTaskStore:          # implements TaskStore
    def __init__(self, max_tasks: int = MAX_TASKS) -> None: ...
    # add(): under lock: if count >= max_tasks raise; id = str(uuid4()); created_at = datetime.now(UTC); append

def get_task_store(request: Request) -> TaskStore:
    return request.app.state.task_store
```

Test seam (for testers): `app.dependency_overrides[get_task_store] = lambda: store` with a fresh `InMemoryTaskStore()` isolates a test and simulates a restart (AC-001.6); filling it to the limit is `for i in range(MAX_TASKS): store.add(f"t{i}", None)` (AC-001.7). Tests must remove their override afterwards.

## Contract

Task object (every response that returns a task):

```json
{"id": "3f2b8c1e-…", "title": "Buy milk", "due_date": "2026-12-24", "created_at": "2026-11-20T10:15:30.123456Z"}
```

| Field | Type | Rule |
|---|---|---|
| `id` | string | server-assigned UUID4, non-empty, opaque; a client-sent `id` is ignored (A3) |
| `title` | string | stored trimmed, 1–200 characters after trimming (A1) |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, past dates allowed (A2) |
| `created_at` | string | ISO 8601 UTC with `Z` suffix, set by the server at creation (A5) |

**`POST /tasks`** — body `application/json` `{"title": string, "due_date"?: string | null}`; unknown fields are ignored (A6).

| Status | When | Body |
|---|---|---|
| `201` | valid input, fewer than 10,000 tasks held | the task object (AC-001.1, AC-001.2) |
| `422` | `title` missing, not a string, empty or whitespace-only, > 200 chars after trim (AC-001.4); `due_date` present, not `null`, and not a string matching `^\d{4}-\d{2}-\d{2}$` that is a real calendar date (AC-001.5); body not a JSON object | FastAPI standard validation body: `{"detail": [{"type": str, "loc": ["body", "<field>"], "msg": str, "input": any, ...}]}`; `loc[-1]` names the field (`"title"` or `"due_date"`) |
| `507` | 10,000 tasks already held (AC-001.7) | `{"detail": "Task limit of 10000 reached"}` |

No task is stored on any non-`201` answer.

**`GET /tasks`** — `200` with a JSON array of task objects, oldest first, unpaged; `[]` when none (AC-001.3, AC-001.6). No query parameters.

No authentication on either endpoint (A9). The existing `/health`, `/ready`, `/ping`, `/metrics` are unchanged.

## Data

In memory only: a `list[Task]` in `InMemoryTaskStore`, at most `MAX_TASKS` entries, lost on restart; each instance holds its own tasks (A8).

## Smoke

Smoke tests for AC-001.1 and AC-001.2 create tasks: `@pytest.mark.smoke` + `@pytest.mark.writes`, titles `smoke-<uuid>`. AC-001.3's smoke check has a read-only part (`GET /tasks` answers `200` with an array) that runs in every environment, and a writing part (created task appears) marked `writes`.
