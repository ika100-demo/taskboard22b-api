---
spec_id: 001-create-and-list-tasks-in-memory
shape: service-python
spec_hash: 3a6cb4e40626
summary: In-memory POST /tasks and GET /tasks with validation and a 10,000-task limit
tasks:
  - id: t1
    title: Add tasks package (schemas, in-memory store, router) and wire it into the app
    files: [src/taskboard22b_api/tasks/__init__.py, src/taskboard22b_api/tasks/models.py, src/taskboard22b_api/tasks/store.py, src/taskboard22b_api/tasks/api.py, src/taskboard22b_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
---

# Plan — 001 Create and list tasks in memory

See [design.md](design.md) for the binding contract and signatures.

## t1 — Add tasks package (schemas, in-memory store, router) and wire it into the app

**Files:** src/taskboard22b_api/tasks/__init__.py, src/taskboard22b_api/tasks/models.py, src/taskboard22b_api/tasks/store.py, src/taskboard22b_api/tasks/api.py, src/taskboard22b_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Clients can create tasks and list them through the contract in design.md, held in a bounded in-memory store behind a `TaskStore` protocol that a later persistent store can replace. One task, because the store alone has no acceptance check that can pass and the router cannot exist without it.

**Implementation notes:**
- `models.py`: `TaskCreate` with `title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]` and `due_date: date | None = None`, plus a `field_validator("due_date", mode="before")` that passes `None` through, rejects non-strings and strings not matching `^\d{4}-\d{2}-\d{2}$`, then `date.fromisoformat` (invalid dates such as `2026-02-30` raise `ValueError`). Extra fields ignored (Pydantic default).
- `models.py`: `Task` response model (`id: str`, `title: str`, `due_date: date | None`, `created_at: datetime`); serialize `created_at` as UTC with `Z` suffix (e.g. a `field_serializer` producing `isoformat().replace("+00:00", "Z")`).
- `store.py`: `MAX_TASKS = 10_000`, `TaskLimitReachedError`, `TaskStore` protocol, `InMemoryTaskStore(max_tasks=MAX_TASKS)` with a `threading.Lock` around check-and-append; `id = str(uuid4())`, `created_at = datetime.now(UTC)`; `list()` returns a copy in insertion order.
- `api.py`: `router = APIRouter()`; `get_task_store(request)` returns `request.app.state.task_store`; `POST /tasks` (`status_code=201`, `response_model=Task`) maps `TaskLimitReachedError` to `HTTPException(507, "Task limit of 10000 reached")`; `GET /tasks` (`response_model=list[Task]`).
- `main.py`: `app.state.task_store = InMemoryTaskStore()` and `app.include_router(router)`; existing endpoints unchanged.
- Log task creation with structlog (`task_created`, `task_id`; never the title) and the limit refusal (`task_limit_reached`) at warning.
- Keep mypy strict-clean; no new dependencies (FastAPI and Pydantic v2 are already present).

**Done when:** all acceptance tests for AC-001.1 to AC-001.7 pass in-process, and `devbox run ci` is green.
