---
spec_id: 002-persistent-tasks-in-postgres
title: Persistent tasks in Postgres
status: approved
priority: P1
shape: service-python
parent: ika100-demo/taskboard22b-gitops:001-persistent-tasks-in-postgres-with-a-web
---

# 002 — Persistent tasks in Postgres

## Problem

The Task API of taskboard22b holds tasks in memory only: every restart or redeploy empties the list, and a second instance would show a different list. People can only reach tasks by calling the API directly, because the web UI has no task features yet. So the taskboard cannot be used for real work today. Keeping tasks in a Postgres database and offering a page to see and create them makes the system usable end to end.

## System context

Slice of the system plan `001-persistent-tasks-in-postgres-with-a-web` in `ika100-demo/taskboard22b-gitops` for `taskboard22b-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks were created through `POST /tasks`, when the Task API is restarted or redeployed, then `GET /tasks` returns `200` with every one of those tasks, each with the same `id`, `title`, `due_date` and `created_at` it was created with, ordered by creation time oldest first.
- **AC-001.2** Given the Task API runs as 2 instances, when a task is created through one instance, then a `GET /tasks` answered by either instance contains that task.
- **AC-001.6** Given the database is unreachable, when a client sends `GET /tasks` or `POST /tasks`, then the Task API answers `503` with a message that tasks are temporarily unavailable, its readiness check `/ready` answers `503`, and once the database is reachable again the requests succeed with no restart of the Task API.
- **AC-001.8** Given 10,000 tasks exist, when the user submits a valid task in the web UI, then the page shows "The task limit of 10,000 is reached." and keeps the entered values, and the Task API answers the underlying `POST /tasks` with `507` as before.

### Contract

The Task API contract of `taskboard22b-api` spec 001 (its `design.md`) stays as it is (A1); this plan adds the `503` answers and the `/ready` behaviour. Base URL for the web UI: the env var `TASK_API_URL` (`http://taskboard22b-api` in the cluster). No authentication on any endpoint (A10).

**Task object**

```json
{"id": "3f2b8c1e-…", "title": "Buy milk", "due_date": "2026-12-24", "created_at": "2026-11-20T10:15:30.123456Z"}
```

| Field | Type | Rule |
|---|---|---|
| `id` | string | server-assigned UUID, opaque; stays the same across restarts |
| `title` | string | stored trimmed, 1 to 200 characters after trimming |
| `due_date` | string `YYYY-MM-DD` or `null` | calendar date, past dates allowed |
| `created_at` | string | ISO 8601 UTC with `Z`, set by the server at creation, unchanged across restarts |

**`GET /tasks`** — no query parameters.

| Status | When | Body |
|---|---|---|
| `200` | database reachable | JSON array of task objects, oldest first, unpaged; `[]` when none |
| `503` | database unreachable or the query did not finish in time | `{"detail": "Tasks are temporarily unavailable"}` |

**`POST /tasks`** — body `application/json` `{"title": string, "due_date"?: string | null}`; unknown fields ignored. The web UI always sends both fields, `title` trimmed, `due_date` `null` when none was picked.

| Status | When | Body |
|---|---|---|
| `201` | valid input, fewer than 10,000 tasks stored | the task object |
| `422` | invalid `title` or `due_date` (unchanged) | FastAPI standard validation body, see Errors |
| `503` | database unreachable or the statement did not finish in time; nothing stored | `{"detail": "Tasks are temporarily unavailable"}` |
| `507` | 10,000 tasks already stored; nothing stored | `{"detail": "Task limit of 10000 reached"}` |

**`GET /ready`** — `200` `{"status": "ready"}` when a `SELECT 1` on the database succeeds; `503` `{"status": "not ready"}` otherwise. **`GET /health`** stays `200` regardless of the database, so the database being down never restarts the pod.

No events.

### Rules

No shared rules: the one shared input rule (title 1 to 200 characters after trimming, A5) cannot be checked by the rule engine, which needs a rejection body carrying the rule id, while the spec keeps the Task API's FastAPI `422` body unchanged (A1, non-goals); both repos test the rule through their own criteria instead.

The rule in words, identical in both repos: `title` is required, is trimmed of leading and trailing whitespace, and must then be 1 to 200 characters long (200 accepted, 201 rejected, empty and whitespace-only rejected). `due_date` is a real calendar date `YYYY-MM-DD` or `null`; the web UI enforces it by its date field.

### Errors

```yaml
errors:
  status: 422
  body:
    list: detail
    field: loc
    rule: type
    message: msg
  unlisted:
    message: "The task could not be saved. Please try again."
```

The `422` body is FastAPI's: `{"detail": [{"type": str, "loc": ["body", "<field>"], "msg": str, ...}]}`; the field is the last element of `loc` (`title` or `due_date`). `503` and `507` carry a single `{"detail": "<text>"}` object. How the web UI treats each answer:

| Call | Answer | Page shows |
|---|---|---|
| `GET /tasks` | `200` | the list, or "No tasks yet" for `[]` |
| `GET /tasks` | `503`, any other status, a body that is not an array, connection error, timeout | "Tasks cannot be loaded right now. Please try again later." instead of the list |
| `POST /tasks` | `201` | the returned task appended to the list, form emptied |
| `POST /tasks` | `422` naming `title` | "Title must be 1 to 200 characters" next to the title field, values kept |
| `POST /tasks` | `507` | "The task limit of 10,000 is reached.", values kept |
| `POST /tasks` | `503`, `422` naming anything else, any other status, connection error, timeout | "The task could not be saved. Please try again.", values kept |

### Timeouts

- **Web UI → Task API**, `GET /tasks` and `POST /tasks`: 5 seconds per call (connect plus response), from the Next.js server. No automatic retry (a retried `POST` could create a task twice); the user retries by reloading or submitting again. Down or slow: treated as unavailable, see Errors.
- **Task API → Postgres**: connect timeout 2 seconds, statement timeout 3 seconds, so the Task API answers `503` within 6 seconds when the database is down or slow, before the web UI's 5-second timeout in the usual case of a refused connection. The connection pool drops broken connections and reconnects on the next request, so the Task API recovers with no restart (A7).
- **`GET /ready`**: the database check gives up after 1 second and answers `503`; Kubernetes then removes the instance from the Service until the check succeeds again, and `/health` keeps the pod alive.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`
- replicas `2` in `dev`

### Notes for this repo

Withdraw assumption A8 of docs/specs/001-create-and-list-tasks-in-memory (one instance, each holding its own tasks): tasks now live in the shared Postgres database.
Connection comes from DATABASE_URL (and PG*), injected by the gitops entry; never a default credential in code.
The request/response contract of spec 001 (fields, 422 body, 201, 507, ordering) stays unchanged; only the 503 and /ready behaviour are new.
Ordering oldest first must stay stable for equal created_at (insertion order, e.g. a sequence column).

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given tasks were created through `POST /tasks` and the database is reachable through `DATABASE_URL`, when the service is restarted (a new process against the same database), then `GET /tasks` returns `200` with every one of those tasks, each with the same `id`, `title`, `due_date` and `created_at` it was created with, ordered by creation time oldest first (system AC-001.1) (replaces AC-001.6)
- **AC-002.2** Given an empty database without the service's tables, when the service starts, then it creates its schema itself and `GET /tasks` returns `200` with `[]` (system AC-001.1)
- **AC-002.3** Given two instances of the service use the same database, when a task is created through `POST /tasks` on one instance, then `GET /tasks` on the other instance contains that task with the same `id`, `title`, `due_date` and `created_at` (system AC-001.2)
- **AC-002.4** Given the database holds 10,000 tasks, when clients send valid `POST /tasks` requests, also concurrently through two instances, then each answers `507` with `{"detail": "Task limit of 10000 reached"}` and the task count stays at 10,000 (system AC-001.8, AC-001.2)
- **AC-002.5** Given the database is unreachable, when a client sends `GET /tasks` or a valid `POST /tasks`, then the service answers `503` with `{"detail": "Tasks are temporarily unavailable"}` within 6 seconds, no task is created, and `GET /ready` answers `503` while `GET /health` stays `200` (system AC-001.6)
- **AC-002.6** Given the database was unreachable and becomes reachable again, when a client sends `GET /ready`, `GET /tasks` and a valid `POST /tasks`, then they answer `200`, `200` and `201` without a restart of the service (system AC-001.6)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-20 created from the system plan, with its criteria (spec 147)
- 2026-11-20 approved
