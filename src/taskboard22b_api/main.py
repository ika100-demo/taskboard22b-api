"""FastAPI entry point for taskboard22b-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import PostgresTaskStore, get_task_store
from .tasks import router as tasks_router
from .tasks.postgres import conninfo_from_env
from .tasks.store import TaskStore
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


class HealthResponse(BaseModel):
    status: str


def create_app(database_url: str | None = None) -> FastAPI:
    """Build the application; the Postgres store is opened at startup, closed at shutdown."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = PostgresTaskStore(database_url or conninfo_from_env())
        store.open()
        app.state.task_store = store
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="taskboard22b-api", version=__version__, lifespan=lifespan)
    app.include_router(tasks_router)
    app.add_middleware(MetricsMiddleware)
    if tracing_enabled():
        FastAPIInstrumentor.instrument_app(app)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse)
    def ready(store: Annotated[TaskStore, Depends(get_task_store)]) -> Response:
        """Readiness probe — 200 when the database answers, else 503."""
        if store.ping(1.0):
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "not ready"}, status_code=503)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard22b-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
