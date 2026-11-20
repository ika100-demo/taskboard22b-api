"""Task schemas: the request and response contract."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, field_serializer, field_validator
from pydantic.types import StringConstraints

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TaskCreate(BaseModel):
    """Body of POST /tasks; unknown fields are ignored."""

    title: Title
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, value: Any) -> date | None:
        if value is None:
            return None
        if not isinstance(value, str) or not _DATE_RE.match(value):
            raise ValueError("due_date must be a date in the format YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a real calendar date") from exc


class Task(BaseModel):
    """A task as returned by the API."""

    id: str
    title: str
    due_date: date | None
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
