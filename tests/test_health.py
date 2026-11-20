"""Smoke tests for health/ready/ping endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_ready(client: TestClient) -> None:
    from taskboard22b_api.main import app
    from taskboard22b_api.tasks import InMemoryTaskStore, get_task_store

    app.dependency_overrides[get_task_store] = lambda: InMemoryTaskStore()
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_task_store, None)
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ping_returns_project_name(client: TestClient) -> None:
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": "taskboard22b-api"}
