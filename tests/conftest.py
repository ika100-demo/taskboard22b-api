"""Shared pytest fixtures."""

from __future__ import annotations

import os
import socket
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient

from taskboard22b_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


def _plain_url(url: str) -> str:
    """Drop a SQLAlchemy-style driver suffix from the scheme."""
    parts = urlsplit(url)
    scheme = parts.scheme.split("+")[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))


@pytest.fixture(scope="session")
def _db_server() -> Iterator[Callable[[], str]]:
    """Lazily start (or look up) a Postgres server; returns its URL when called.

    Nothing starts until a test calls it, so the rest of the suite runs without Docker.
    """
    state: dict[str, Any] = {}

    def server_url() -> str:
        if "url" not in state:
            configured = os.environ.get("TEST_DATABASE_URL")
            if configured:
                state["url"] = _plain_url(configured)
            else:
                from testcontainers.postgres import PostgresContainer

                container = PostgresContainer("postgres:17-alpine")
                container.start()
                state["container"] = container
                state["url"] = _plain_url(container.get_connection_url())
        return str(state["url"])

    yield server_url
    container = state.get("container")
    if container is not None:
        container.stop()


@pytest.fixture()
def new_database(_db_server: Callable[[], str]) -> Iterator[Callable[[], str]]:
    """Return a function creating a fresh empty database `t_<uuid hex>` and giving its URL.

    Every database created is dropped after the test.
    """
    created: list[str] = []

    def make() -> str:
        try:  # no point preparing a database before the app factory exists
            from taskboard22b_api.main import create_app  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"create_app is missing: {exc}")
        import psycopg

        server = _db_server()
        name = f"t_{uuid.uuid4().hex}"
        with psycopg.connect(server, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        created.append(name)
        return _with_database(server, name)

    yield make
    if created:
        import psycopg

        with psycopg.connect(_db_server(), autocommit=True) as conn:
            for name in created:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


class Forwarder:
    """A TCP forwarder between the app and the database; cut() / restore() simulate an outage."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self._target = (target_host, target_port)
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._listener: socket.socket | None = None
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port: int = probe.getsockname()[1]
        probe.close()

    def start(self) -> None:
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen(50)
        with self._lock:
            self._listener = listener
        threading.Thread(target=self._accept, args=(listener,), daemon=True).start()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            try:
                upstream = socket.create_connection(self._target, timeout=5)
            except OSError:
                client.close()
                continue
            upstream.settimeout(None)
            with self._lock:
                self._sockets.extend([client, upstream])
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (src, dst):
                try:
                    sock.close()
                except OSError:
                    pass

    def cut(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
            sockets, self._sockets = self._sockets, []
        if listener is not None:
            try:  # on Linux close() alone leaves a blocked accept() listening
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def restore(self) -> None:
        self.start()


@pytest.fixture()
def forward_database() -> Iterator[Callable[[str], tuple[str, Forwarder]]]:
    """Return a function that puts a forwarder in front of a database URL: (url, forwarder)."""
    forwarders: list[Forwarder] = []

    def forward(url: str) -> tuple[str, Forwarder]:
        parts = urlsplit(url)
        forwarder = Forwarder(parts.hostname or "127.0.0.1", parts.port or 5432)
        forwarder.start()
        forwarders.append(forwarder)
        userinfo = parts.netloc.rpartition("@")[0]
        host = f"127.0.0.1:{forwarder.port}"
        netloc = f"{userinfo}@{host}" if userinfo else host
        new_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return new_url, forwarder

    yield forward
    for forwarder in forwarders:
        forwarder.cut()
