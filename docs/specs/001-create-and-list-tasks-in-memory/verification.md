# Verification — 001 Create and list tasks in memory

**Result:** pass
**Commit:** 79dc3c2 · **Base:** 8c3ea0d · **Trace:** 7/7 criteria named by tests (AC-001.1–3 also by smoke tests)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks_acceptance.py::test_create_task_201`, `::test_create_task_ignores_client_id_and_trims_title`; smoke `tests/test_smoke_tasks.py::test_smoke_create_task` | `src/taskboard22b_api/tasks/api.py:25`, `src/taskboard22b_api/tasks/store.py:40-46`, `src/taskboard22b_api/tasks/models.py:44-46` | asserts 201, non-empty string `id`, title, due_date, `created_at` matching ISO 8601 with `Z` and parseable, two different ids |
| AC-001.2 | met | `tests/test_tasks_acceptance.py::test_create_task_without_due_date`, `::test_create_task_with_null_due_date`; smoke `tests/test_smoke_tasks.py::test_smoke_create_task_without_due_date` | `src/taskboard22b_api/tasks/models.py:21,26-27` | both omitted and explicit `null` give 201 with `due_date` null |
| AC-001.3 | met | `tests/test_tasks_acceptance.py::test_list_oldest_first`; smoke `tests/test_smoke_tasks.py::test_smoke_list_tasks_read_only`, `::test_smoke_created_task_is_listed` | `src/taskboard22b_api/tasks/api.py:36-38`, `src/taskboard22b_api/tasks/store.py:46,49-51` | 200, array, order by creation, values and ids equal to the create responses, shape checked per item |
| AC-001.4 | met | `tests/test_tasks_acceptance.py::test_invalid_title_422` (missing, 123, null, empty, whitespace, 201 chars, 201 chars padded), `::test_title_of_200_chars_after_trim_is_accepted` | `src/taskboard22b_api/tasks/models.py:14,20` | 422 with `loc[-1] == "title"`, `GET /tasks` stays `[]`; 200-char boundary accepted |
| AC-001.5 | met | `tests/test_tasks_acceptance.py::test_invalid_due_422` (`24.12.2026`, `2026-02-30`, `2026-12-24T10:00:00Z`, `""`, `tomorrow`, integer) | `src/taskboard22b_api/tasks/models.py:12,23-33` | 422 with `loc[-1] == "due_date"`, no task created |
| AC-001.6 | met | `tests/test_tasks_acceptance.py::test_restart_yields_empty_list` | `src/taskboard22b_api/main.py:25`, `src/taskboard22b_api/tasks/store.py:33` | restart simulated by installing a fresh store (design's test seam); the store is process memory created at import, so a real restart starts empty |
| AC-001.7 | met | `tests/test_tasks_acceptance.py::test_task_limit_returns_507` | `src/taskboard22b_api/tasks/store.py:13,38-39`, `src/taskboard22b_api/tasks/api.py:29-31` | 507 with `{"detail": "Task limit of 10000 reached"}`, list length stays 10,000; `MAX_TASKS == 10_000` asserted |

## Non-goals

No persistence, update/complete/delete, get-by-id, filtering/paging, users or authentication code was added; `due_date` is a plain date. No template-owned layout (existing `/health`, `/ready`, `/ping`, `/metrics`) changed; `main.py` only adds the store and the router. ✔

## Deviations from the plan

None. Every changed source file is in t1's `files`; t1 is `done: true`; test files and spec/plan/design are the build's own artefacts.

## Contract

Matches `design.md`: fields, status codes 201/422/507, the 507 body, `Z`-suffixed `created_at`, client `id` ignored, `TaskStore` protocol and `get_task_store` seam as specified. No `contract/` copy exists, so no provider contract cases apply. ✔

## Mutation check (report only)

16 of 19 mutants of the changed code were caught by the acceptance tests (84 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard22b_api/tasks/api.py:19 return value → None`
- `src/taskboard22b_api/tasks/models.py:14 1 → 2`
- `src/taskboard22b_api/tasks/store.py:55 return value → None`
