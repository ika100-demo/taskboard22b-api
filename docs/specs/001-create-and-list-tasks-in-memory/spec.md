---
spec_id: 001-create-and-list-tasks-in-memory
title: Create and list tasks in memory
status: draft
priority: P1
shape: service-python
---

# 001 — Create and list tasks in memory

## Problem

The Task API can only report its own health today, so no client of the taskboard22b system can record or show any work. Users of the taskboard need to capture tasks, optionally with a date they are due, and see what they have captured. A first, in-memory version lets the system's clients build against a real task contract now, before any persistence is chosen.

## Stories

As a taskboard user, I want to create a task with a title and, if I like, a due date, so that I can capture work as it comes up.

As a taskboard user, I want to list all tasks I have created, so that I can see what is still to do and when it is due.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with body `{"title": "Buy milk", "due_date": "2026-12-24"}`, then the response is `201` with a JSON task holding a server-assigned non-empty string `id`, `title` `"Buy milk"`, `due_date` `"2026-12-24"` and `created_at` as an ISO 8601 UTC timestamp, and two such requests yield two different `id`s. (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with body `{"title": "Call Anna"}` (no `due_date`, or `"due_date": null`), then the response is `201` with a task whose `due_date` is `null`. (smoke)
- **AC-001.3** Given tasks were created on the running service, when a client sends `GET /tasks`, then the response is `200` with a JSON array of all tasks in the same shape as AC-001.1, ordered by creation time oldest first, each with the values it was created with. (smoke)
- **AC-001.4** Given a running service, when a client sends `POST /tasks` with `title` missing, not a string, empty, only whitespace, or longer than 200 characters after trimming leading and trailing whitespace, then the response is `422` naming the field `title`, and `GET /tasks` does not contain a new task.
- **AC-001.5** Given a running service, when a client sends `POST /tasks` with a valid title and a `due_date` that is not a real calendar date in the form `YYYY-MM-DD` (for example `"24.12.2026"`, `"2026-02-30"` or `"2026-12-24T10:00:00Z"`), then the response is `422` naming the field `due_date`, and no task is created.
- **AC-001.6** Given tasks were created, when the service restarts, then `GET /tasks` returns `200` with an empty array `[]`.
- **AC-001.7** Given the service already holds 10,000 tasks, when a client sends a valid `POST /tasks`, then the response is `507` with a message that the task limit is reached, and the task count stays at 10,000.

## Non-goals

- Persisting tasks across restarts or sharing them between service instances.
- Updating, completing or deleting tasks; fetching a single task by id.
- Filtering, sorting options, searching or paging the list.
- Users, ownership or per-user task lists.
- Authentication or authorization of callers.
- Times of day or time zones on the due date.

## Assumptions

- **A1** The title is trimmed of leading and trailing whitespace and stored trimmed; 1 to 200 characters are allowed (other option: no trimming, 500 characters; affects AC-001.1, AC-001.4).
- **A2** `due_date` is a calendar date `YYYY-MM-DD` without time; dates in the past are accepted (other option: reject past dates; affects AC-001.1, AC-001.5).
- **A3** The `id` is an opaque server-assigned string (a UUID), never supplied by the client (other option: increasing integers; affects AC-001.1).
- **A4** The list is ordered by creation, oldest first, and returned unpaged (other option: newest first; affects AC-001.3).
- **A5** Each response carries `created_at` so clients can show and order tasks (other option: no timestamp; affects AC-001.1, AC-001.3).
- **A6** Invalid input answers `422` with the framework's standard validation body naming the field; unknown extra fields in the body are ignored (other option: `400` with a custom body, reject unknown fields; affects AC-001.4, AC-001.5).
- **A7** At most 10,000 tasks are held, beyond that creating answers `507`, so that memory stays bounded (other option: no limit, or drop the oldest; affects AC-001.7).
- **A8** The service runs as one instance; with several instances each would hold and list its own tasks (other option: shared store, which is out of scope here; affects AC-001.3, AC-001.6).
- **A9** Create and list are open to every caller that reaches the service; no authentication in this first version (other option: shared API key or cluster-internal only; affects AC-001.1, AC-001.2, AC-001.3).

## Notes for the architect

- The in-memory store is meant to be replaced by persistence later; keep the task contract (fields, status codes) independent of how tasks are held.
- Smoke tests that create tasks must be marked writing and use `smoke-<uuid>` titles; `GET /tasks` serves as the read-only smoke check for staging and prod.

## Open questions

- ~~Do create and list stay open to every caller that reaches the service, without authentication, in this first version? (suggested: yes, no authentication, the data is in memory only and holds no personal data; alternatives: require a shared API key from an environment secret; or restrict exposure to inside the cluster only; affects AC-001.1, AC-001.2, AC-001.3)~~ Answered 2026-11-20: yes, no authentication; see A9 and Non-goals.

## Changelog

- 2026-11-20 created
- 2026-11-20 priority P1 proposed: P1: normal bug or feature
- 2026-11-20 amended: open question on authentication answered (no authentication), recorded as A9 and a non-goal
