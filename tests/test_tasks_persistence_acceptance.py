"""Acceptance tests for spec 002: persistent tasks in Postgres."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient

UNAVAILABLE = {"detail": "Tasks are temporarily unavailable"}
LIMIT = {"detail": "Task limit of 10000 reached"}


@pytest.fixture()
def make_app() -> Iterator[Callable[[str], TestClient]]:
    """Return a function starting one app instance (lifespan run) against a database URL."""
    stack = ExitStack()

    def start(url: str) -> TestClient:
        try:
            from taskboard22b_api.main import create_app
        except ImportError as exc:
            pytest.fail(f"create_app is missing: {exc}")
        return stack.enter_context(TestClient(create_app(database_url=url)))

    yield start
    stack.close()


def _fill(url: str, count: int) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, created_at) "
            "SELECT gen_random_uuid(), 't' || g, clock_timestamp() "
            "FROM generate_series(1, %s) g",
            (count,),
        )


def _count(url: str) -> int:
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT count(*) FROM tasks").fetchone()
    assert row is not None
    return int(row[0])


def _wait_ready(client: TestClient, seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if client.get("/ready").status_code == 200:
            return
        time.sleep(0.5)
    pytest.fail(f"/ready did not become 200 within {seconds} s")


def test_tasks_survive_restart(new_database: Any) -> None:  # AC-002.1
    try:
        from taskboard22b_api.main import create_app
    except ImportError as exc:
        pytest.fail(f"create_app is missing: {exc}")
    url = new_database()
    payloads = [
        {"title": "Buy milk", "due_date": "2026-12-24"},
        {"title": "Call Anna"},
        {"title": "Third"},
    ]
    created = []
    with TestClient(create_app(database_url=url)) as first:
        for payload in payloads:
            response = first.post("/tasks", json=payload)
            assert response.status_code == 201
            created.append(response.json())

    with TestClient(create_app(database_url=url)) as second:  # the restart
        listed = second.get("/tasks")
        assert listed.status_code == 200
        assert listed.json() == created
        assert [t["title"] for t in listed.json()] == ["Buy milk", "Call Anna", "Third"]
        assert [t["due_date"] for t in listed.json()] == ["2026-12-24", None, None]


def test_empty_database_gets_schema_and_lists_empty(
    new_database: Any, make_app: Any
) -> None:  # AC-002.2
    url = new_database()
    client = make_app(url)
    assert _count(url) == 0  # the schema exists right after start, before any request
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_two_instances_starting_together_share_schema(
    new_database: Any, make_app: Any
) -> None:  # AC-002.2
    url = new_database()
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(make_app, [url, url])
    assert a.get("/tasks").json() == []
    assert b.get("/tasks").json() == []


def test_task_created_on_one_instance_visible_on_other(
    new_database: Any, make_app: Any
) -> None:  # AC-002.3
    url = new_database()
    a = make_app(url)
    b = make_app(url)
    made = a.post("/tasks", json={"title": "Shared", "due_date": "2027-01-01"})
    assert made.status_code == 201
    other = b.post("/tasks", json={"title": "Second"})
    assert other.status_code == 201
    from_b = b.get("/tasks")
    assert from_b.status_code == 200
    assert from_b.json() == [made.json(), other.json()]
    assert a.get("/tasks").json() == [made.json(), other.json()]


def test_limit_507_with_10000_tasks_across_instances(
    new_database: Any, make_app: Any
) -> None:  # AC-002.4
    url = new_database()
    a = make_app(url)
    b = make_app(url)
    assert a.get("/tasks").status_code == 200  # schema exists
    _fill(url, 10_000)
    single = a.post("/tasks", json={"title": "one too many"})
    assert single.status_code == 507
    assert single.json() == LIMIT

    def post(client: TestClient) -> Any:
        return client.post("/tasks", json={"title": "concurrent"})

    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(post, [a, b] * 6))
    assert [r.status_code for r in responses] == [507] * 12
    assert all(r.json() == LIMIT for r in responses)
    assert _count(url) == 10_000


def test_limit_never_exceeded_by_concurrent_instances(
    new_database: Any, make_app: Any
) -> None:  # AC-002.4
    url = new_database()
    a = make_app(url)
    b = make_app(url)
    assert a.get("/tasks").status_code == 200
    _fill(url, 9_998)

    def post(client: TestClient) -> Any:
        return client.post("/tasks", json={"title": "race"})

    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(post, [a, b] * 4))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 201] + [507] * 6
    assert _count(url) == 10_000


def test_database_unreachable_answers_503(
    new_database: Any, forward_database: Any, make_app: Any
) -> None:  # AC-002.5
    url, forwarder = forward_database(new_database())
    client = make_app(url)
    assert client.post("/tasks", json={"title": "before"}).status_code == 201
    forwarder.cut()

    started = time.monotonic()
    listed = client.get("/tasks")
    assert time.monotonic() - started < 6
    assert listed.status_code == 503
    assert listed.json() == UNAVAILABLE

    started = time.monotonic()
    posted = client.post("/tasks", json={"title": "during"})
    assert time.monotonic() - started < 6
    assert posted.status_code == 503
    assert posted.json() == UNAVAILABLE

    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}

    forwarder.restore()
    _wait_ready(client)
    titles = [t["title"] for t in client.get("/tasks").json()]
    assert titles == ["before"]  # nothing was created while down


def test_service_started_with_database_down_answers_503(
    new_database: Any, forward_database: Any, make_app: Any
) -> None:  # AC-002.5
    url, forwarder = forward_database(new_database())
    forwarder.cut()
    client = make_app(url)  # starting must not fail
    started = time.monotonic()
    response = client.get("/tasks")
    assert time.monotonic() - started < 6
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    assert client.get("/ready").status_code == 503
    assert client.get("/health").status_code == 200


def test_recovery_without_restart(
    new_database: Any, forward_database: Any, make_app: Any
) -> None:  # AC-002.6
    url, forwarder = forward_database(new_database())
    client = make_app(url)
    assert client.get("/tasks").status_code == 200
    forwarder.cut()
    assert client.get("/ready").status_code == 503
    assert client.get("/tasks").status_code == 503

    forwarder.restore()
    _wait_ready(client)
    assert client.get("/ready").status_code == 200
    assert client.get("/tasks").status_code == 200
    created = client.post("/tasks", json={"title": "after"})
    assert created.status_code == 201
    assert client.get("/tasks").json() == [created.json()]


def test_recovery_when_started_with_database_down(
    new_database: Any, forward_database: Any, make_app: Any
) -> None:  # AC-002.6
    url, forwarder = forward_database(new_database())
    forwarder.cut()
    client = make_app(url)
    assert client.get("/ready").status_code == 503

    forwarder.restore()
    _wait_ready(client)
    assert client.get("/tasks").status_code == 200
    assert client.get("/tasks").json() == []
    assert client.post("/tasks", json={"title": "after"}).status_code == 201
