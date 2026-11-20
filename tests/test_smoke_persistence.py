"""Smoke tests for spec 002 (persistence); they reach the service only through SMOKE_BASE_URL."""

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
def test_smoke_ready_and_list_reach_database(smoke_base_url: str) -> None:  # AC-002.1
    status, ready = _request(smoke_base_url, "GET", "/ready")
    assert status == 200
    assert ready == {"status": "ready"}
    status, body = _request(smoke_base_url, "GET", "/tasks")
    assert status == 200
    assert isinstance(body, list)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_created_task_is_stable_across_replicas(smoke_base_url: str) -> None:  # AC-002.3
    title = f"smoke-{uuid.uuid4()}"
    _, created = _request(smoke_base_url, "POST", "/tasks", {"title": title})
    for _ in range(6):  # requests land on both replicas through the Service
        status, body = _request(smoke_base_url, "GET", "/tasks")
        assert status == 200
        found = [t for t in body if t["id"] == created["id"]]
        assert len(found) == 1
        assert found[0]["created_at"] == created["created_at"]
        assert found[0]["title"] == title
