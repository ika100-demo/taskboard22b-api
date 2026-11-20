"""HTTP routes for tasks."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from .models import Task, TaskCreate
from .store import MAX_TASKS, TaskLimitReachedError, TaskStore, TaskStoreUnavailableError

UNAVAILABLE_DETAIL = "Tasks are temporarily unavailable"

router = APIRouter()
log = structlog.get_logger()


def get_task_store(request: Request) -> TaskStore:
    store: TaskStore = request.app.state.task_store
    return store


StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(body: TaskCreate, store: StoreDep) -> Task:
    try:
        task = store.add(body.title, body.due_date)
    except TaskLimitReachedError:
        log.warning("task_limit_reached", limit=MAX_TASKS)
        raise HTTPException(status_code=507, detail=f"Task limit of {MAX_TASKS} reached") from None
    except TaskStoreUnavailableError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    log.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: StoreDep) -> list[Task]:
    try:
        return store.list()
    except TaskStoreUnavailableError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
