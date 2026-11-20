"""Smoke tests for spec 001 (tasks); they reach the service only through SMOKE_BASE_URL."""

from __future__ import annotations

import json
import urllib.request
import uuid
from typing import Any

import pytest


def _request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    status, task = _request(
        smoke_base_url, "POST", "/tasks", {"title": title, "due_date": "2026-12-24"}
    )
    assert status == 201
    assert task["title"] == title
    assert task["due_date"] == "2026-12-24"
    assert isinstance(task["id"], str) and task["id"]
    assert task["created_at"].endswith("Z")
    _, other = _request(smoke_base_url, "POST", "/tasks", {"title": f"smoke-{uuid.uuid4()}"})
    assert other["id"] != task["id"]


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_create_task_without_due_date(smoke_base_url: str) -> None:  # AC-001.2
    status, task = _request(smoke_base_url, "POST", "/tasks", {"title": f"smoke-{uuid.uuid4()}"})
    assert status == 201
    assert task["due_date"] is None


@pytest.mark.smoke
def test_smoke_list_tasks_read_only(smoke_base_url: str) -> None:  # AC-001.3
    status, body = _request(smoke_base_url, "GET", "/tasks")
    assert status == 200
    assert isinstance(body, list)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_created_task_is_listed(smoke_base_url: str) -> None:  # AC-001.3
    title = f"smoke-{uuid.uuid4()}"
    _, created = _request(smoke_base_url, "POST", "/tasks", {"title": title})
    status, body = _request(smoke_base_url, "GET", "/tasks")
    assert status == 200
    assert [t for t in body if t["id"] == created["id"]] == [created]
