"""Shared test helpers: fake asyncpg database and JWT/profile fixtures.

The fakes are deliberately asyncpg-shaped: services acquire a transaction and
then call ``fetch``/``fetchrow``/``execute`` on the connection, while simple
reads go through the ``Database`` wrapper. Queued results are returned in call
order so tests can drive real service code without a network or Postgres.
"""
from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app

TEST_JWT_SECRET = "test-jwt-secret-not-for-production"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


class FakeTransaction:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> "FakeConnection":
        self.connection.transactions += 1
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.connection.commits += 0 if exc_type else 1
        self.connection.rollbacks += 1 if exc_type else 0
        return False


class FakeConnection:
    """Queue-driven asyncpg connection double."""

    def __init__(self) -> None:
        self.fetchrow_results: deque[Any] = deque()
        self.fetch_results: deque[Any] = deque()
        self.execute_results: deque[str] = deque()
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self.transactions = 0
        self.commits = 0
        self.rollbacks = 0

    def queue_fetchrow(self, *results: Any) -> None:
        self.fetchrow_results.extend(results)

    def queue_fetch(self, *results: Any) -> None:
        self.fetch_results.extend(results)

    def queue_execute(self, *results: str) -> None:
        self.execute_results.extend(results)

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("fetchrow", query, args))
        if not self.fetchrow_results:
            raise AssertionError(f"Unexpected fetchrow call: {query}")
        return self.fetchrow_results.popleft()

    async def fetch(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("fetch", query, args))
        if not self.fetch_results:
            raise AssertionError(f"Unexpected fetch call: {query}")
        return self.fetch_results.popleft()

    async def execute(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("execute", query, args))
        if self.execute_results:
            return self.execute_results.popleft()
        return "INSERT 0 1"

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


class FakeDatabase:
    """Database-wrapper double with one queue-driven connection."""

    def __init__(self, fail_with: BaseException | None = None) -> None:
        self.connection = FakeConnection()
        self.fail_with = fail_with

    def queue_fetchrow(self, *results: Any) -> None:
        self.connection.queue_fetchrow(*results)

    def queue_fetch(self, *results: Any) -> None:
        self.connection.queue_fetch(*results)

    def queue_execute(self, *results: str) -> None:
        self.connection.queue_execute(*results)

    @property
    def calls(self) -> list[tuple[str, str, tuple[Any, ...]]]:
        return self.connection.calls

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None):
        if self.fail_with is not None:
            raise self.fail_with
        return await self.connection.fetchrow(query, *args, timeout=timeout)

    async def fetch(self, query: str, *args: Any, timeout: float | None = None):
        if self.fail_with is not None:
            raise self.fail_with
        return await self.connection.fetch(query, *args, timeout=timeout)

    async def execute(self, query: str, *args: Any, timeout: float | None = None):
        if self.fail_with is not None:
            raise self.fail_with
        return await self.connection.execute(query, *args, timeout=timeout)

    def transaction(self) -> FakeTransaction:
        if self.fail_with is not None:
            raise self.fail_with
        return self.connection.transaction()


def profile_row(
    *,
    user_id: str | UUID | None = None,
    email: str = "user@example.test",
    is_approved: bool = False,
    app_role: str = "user",
    approved_at: datetime | None = None,
    approved_by: str | UUID | None = None,
) -> dict[str, Any]:
    return {
        "id": user_id or uuid4(),
        "email": email,
        "is_approved": is_approved,
        "app_role": app_role,
        "approved_at": approved_at,
        "approved_by": approved_by,
        "created_at": NOW,
        "updated_at": NOW,
    }


def job_row(
    *,
    job_id: str | UUID | None = None,
    user_id: str | UUID | None = None,
    status: str = "queued",
    **overrides: Any,
) -> dict[str, Any]:
    """A complete ``download_jobs`` row for service and API tests."""
    row: dict[str, Any] = {
        "id": job_id or uuid4(),
        "user_id": user_id or uuid4(),
        "asset_id": None,
        "playlist_id": None,
        "kind": "video",
        "source_url": "https://example.test/video",
        "title": "",
        "options_hash": "a" * 64,
        "format_selector": "best",
        "idempotency_key": None,
        "status": status,
        "progress": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed": 0,
        "eta_seconds": None,
        "error": "",
        "attempts": 0,
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": None,
        "completed_at": None,
        "cancel_requested": False,
        "item_index": 0,
        "item_count": 0,
        "current_item_title": "",
        "current_item_progress": 0,
    }
    row.update(overrides)
    return row


def asset_row(
    *,
    asset_id: str | UUID | None = None,
    status: str = "processing",
    **overrides: Any,
) -> dict[str, Any]:
    """A complete ``media_assets`` row for service and worker tests."""
    row: dict[str, Any] = {
        "id": asset_id or uuid4(),
        "canonical_id": "youtube:vid1",
        "extractor_key": "youtube",
        "source_url": "https://example.test/video",
        "title": "Clip",
        "duration_seconds": 12,
        "options_hash": "b" * 64,
        "options_schema_version": 1,
        "format_selector": "best",
        "output_ext": None,
        "file_path": None,
        "thumbnail_path": None,
        "file_size_bytes": None,
        "file_sha256": None,
        "status": status,
        "error": "",
        "attempts": 1,
        "claimed_at": None,
        "lease_until": None,
        "created_at": NOW,
        "updated_at": NOW,
        "last_accessed_at": NOW,
    }
    row.update(overrides)
    return row


def make_settings(tmp_path, **overrides: Any) -> Settings:
    env = {
        "ENVIRONMENT": "test",
        "SUPABASE_JWT_SECRET": TEST_JWT_SECRET,
        "SUPABASE_JWT_AUDIENCE": "authenticated",
        "DOWNLOAD_DIR": str(tmp_path / "downloads"),
        "FRONTEND_DIST": str(tmp_path / "frontend-dist"),
    }
    env.update({key: str(value) for key, value in overrides.items()})
    return Settings.from_env(env)


def make_token(
    subject: str | UUID,
    *,
    secret: str = TEST_JWT_SECRET,
    audience: str = "authenticated",
    expires_in: int = 3600,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(subject),
            "aud": audience,
            "iat": now,
            "exp": now + expires_in,
        },
        secret,
        algorithm="HS256",
    )


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def app_client(
    settings: Settings,
    db: FakeDatabase | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> Iterator[tuple[Any, TestClient]]:
    app = create_app(settings)
    with TestClient(
        app, raise_server_exceptions=raise_server_exceptions
    ) as client:
        # The lifespan installs the real (absent) pool; tests inject their fake
        # after startup so request handling exercises the same dependencies.
        if db is not None:
            app.state.db = db
        yield app, client
