"""Acceptance tests for spec 001: create and list tasks in memory."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard22b_api.main import app

CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


@pytest.fixture()
def use_store() -> Iterator[Callable[[], Any]]:
    """Return a function that installs a fresh store; imports happen in the test body."""
    installed: list[Any] = []

    def install() -> Any:
        try:
            from taskboard22b_api.tasks import InMemoryTaskStore, get_task_store
        except ImportError as exc:
            pytest.fail(f"taskboard22b_api.tasks is missing: {exc}")
        store = InMemoryTaskStore()
        app.dependency_overrides[get_task_store] = lambda: store
        installed.append(get_task_store)
        return store

    yield install
    for dep in installed:
        app.dependency_overrides.pop(dep, None)


def _assert_task_shape(task: dict[str, Any]) -> None:
    assert set(task) >= {"id", "title", "due_date", "created_at"}
    assert isinstance(task["id"], str)
    assert task["id"]
    assert isinstance(task["created_at"], str)
    assert CREATED_AT_RE.match(task["created_at"]), task["created_at"]
    datetime.fromisoformat(task["created_at"].replace("Z", "+00:00"))


def _loc_fields(response: Any) -> list[str]:
    return [str(err["loc"][-1]) for err in response.json()["detail"]]


def test_create_task_201(client: TestClient, use_store: Any) -> None:  # AC-001.1
    use_store()
    first = client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-24"})
    assert first.status_code == 201
    body = first.json()
    _assert_task_shape(body)
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-24"
    second = client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-24"})
    assert second.status_code == 201
    assert second.json()["id"] != body["id"]


def test_create_task_ignores_client_id_and_trims_title(
    client: TestClient, use_store: Any
) -> None:  # AC-001.1
    use_store()
    response = client.post("/tasks", json={"id": "mine", "title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["id"] != "mine"
    assert response.json()["title"] == "Buy milk"


def test_create_task_without_due_date(client: TestClient, use_store: Any) -> None:  # AC-001.2
    use_store()
    response = client.post("/tasks", json={"title": "Call Anna"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_create_task_with_null_due_date(client: TestClient, use_store: Any) -> None:  # AC-001.2
    use_store()
    response = client.post("/tasks", json={"title": "Call Anna", "due_date": None})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_list_oldest_first(client: TestClient, use_store: Any) -> None:  # AC-001.3
    use_store()
    created = []
    for title, due in [("one", "2026-12-24"), ("two", None), ("three", "2027-01-01")]:
        response = client.post("/tasks", json={"title": title, "due_date": due})
        assert response.status_code == 201
        created.append(response.json())
    listed = client.get("/tasks")
    assert listed.status_code == 200
    body = listed.json()
    assert isinstance(body, list)
    assert [t["title"] for t in body] == ["one", "two", "three"]
    assert [t["due_date"] for t in body] == ["2026-12-24", None, "2027-01-01"]
    assert [t["id"] for t in body] == [t["id"] for t in created]
    assert body == created
    for task in body:
        _assert_task_shape(task)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"due_date": "2026-12-24"},
        {"title": 123},
        {"title": None},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": " " + "x" * 201 + " "},
    ],
)
def test_invalid_title_422(client: TestClient, use_store: Any, payload: dict) -> None:  # AC-001.4
    use_store()
    response = client.post("/tasks", json=payload)
    assert response.status_code == 422
    assert "title" in _loc_fields(response)
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert listed.json() == []


def test_title_of_200_chars_after_trim_is_accepted(
    client: TestClient, use_store: Any
) -> None:  # AC-001.4
    use_store()
    response = client.post("/tasks", json={"title": " " + "x" * 200 + " "})
    assert response.status_code == 201
    assert response.json()["title"] == "x" * 200


@pytest.mark.parametrize(
    "due", ["24.12.2026", "2026-02-30", "2026-12-24T10:00:00Z", "", "tomorrow", 20261224]
)
def test_invalid_due_422(client: TestClient, use_store: Any, due: object) -> None:  # AC-001.5
    use_store()
    response = client.post("/tasks", json={"title": "Buy milk", "due_date": due})
    assert response.status_code == 422
    assert "due_date" in _loc_fields(response)
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert listed.json() == []


def test_task_limit_returns_507(client: TestClient, use_store: Any) -> None:  # AC-001.7
    store = use_store()
    from taskboard22b_api.tasks.store import MAX_TASKS

    assert MAX_TASKS == 10_000
    for i in range(MAX_TASKS):
        store.add(f"t{i}", None)
    response = client.post("/tasks", json={"title": "one too many"})
    assert response.status_code == 507
    assert response.json() == {"detail": "Task limit of 10000 reached"}
    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert len(listed.json()) == MAX_TASKS
