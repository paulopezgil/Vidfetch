"""Tests for the psycopg 3 pool wrapper and the asyncpg-style adapter.

The fake pool and fake psycopg connection exercise the wrapper's real
acquisition, placeholder translation, transaction, and timeout behavior without
a network. ``create_pool`` is tested by monkeypatching the pool class so the
required pooler-safe options (and the explicit open/wait) are asserted.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg.rows import dict_row

from backend.app.core import db as db_module
from backend.app.core.config import ConfigError, Settings
from backend.app.core.db import (
    DB_ERRORS,
    DB_UNAVAILABLE,
    Database,
    adapt_placeholders,
    is_unique_violation,
)
from backend.app.services import assets


class FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> "FakeTransaction":
        self.log.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.log.append("rollback" if exc_type else "commit")
        return False


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection
        self.statusmessage: str | None = None
        self.closed = False

    async def execute(self, query: str, params: Any = None) -> "FakeCursor":
        self.connection.calls.append((query, params))
        if self.connection.delay:
            await asyncio.sleep(self.connection.delay)
        if self.connection.error is not None:
            raise self.connection.error
        self.statusmessage = self.connection.status
        return self

    async def fetchall(self) -> list[Any]:
        return list(self.connection.rows)

    async def fetchone(self) -> Any:
        return self.connection.rows[0] if self.connection.rows else None

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.closed = True
        return False


class FakeConnection:
    """A psycopg-shaped async connection double."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.status = "UPDATE 1"
        self.error: BaseException | None = None
        self.delay = 0.0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.log)

    async def close(self) -> None:
        self.closed = True


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakePool:
    def __init__(self, connection: FakeConnection | None = None) -> None:
        self.log: list[str] = []
        self.connection = connection or FakeConnection(self.log)
        self.acquire_count = 0
        self.closed = False

    def acquire(self) -> FakeAcquire:
        self.acquire_count += 1
        return FakeAcquire(self.connection)

    async def close(self) -> None:
        self.closed = True


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Placeholder adapter
# ---------------------------------------------------------------------------


def test_adapter_rewrites_single_placeholder():
    sql, params = adapt_placeholders(
        "select * from t where id = $1", (7,)
    )

    assert sql == "select * from t where id = %s"
    assert params == (7,)


def test_adapter_duplicates_repeated_arguments_in_occurrence_order():
    sql, params = adapt_placeholders(
        "select $1::int as a, $1::int as b, $2::text as c", (7, "x")
    )

    assert sql == "select %s::int as a, %s::int as b, %s::text as c"
    assert params == (7, 7, "x")


def test_adapter_escapes_percent_literals_and_orders_by_occurrence():
    query = "select * from t where title ilike '%' || $2 || '%' and id = $1"

    sql, params = adapt_placeholders(query, (5, "needle"))

    assert sql == (
        "select * from t where title ilike '%%' || %s || '%%' and id = %s"
    )
    assert params == ("needle", 5)


def test_adapter_is_a_noop_without_arguments():
    assert adapt_placeholders("select 1", ()) == ("select 1", ())
    # A literal percent sign is left alone: psycopg performs no interpolation
    # for parameterless statements.
    assert adapt_placeholders("select '100%'", ()) == ("select '100%'", ())
    assert adapt_placeholders("select $1::int", ()) == (
        "select $1::int",
        (),
    )


def test_adapter_allows_gaps_and_ignores_unused_arguments():
    sql, params = adapt_placeholders("select $1, $3", ("a", "unused", "c"))

    assert sql == "select %s, %s"
    assert params == ("a", "c")


@pytest.mark.parametrize(
    "query, args",
    [
        ("select $0", (1,)),
        ("select $2", (1,)),
        ("select $3", (1, 2)),
        ("select $10", ("a", "b")),
    ],
)
def test_adapter_rejects_out_of_range_indices(query, args):
    with pytest.raises(ValueError, match="argument"):
        adapt_placeholders(query, args)


# ---------------------------------------------------------------------------
# Database wrapper over the adapter
# ---------------------------------------------------------------------------


def test_fetch_translates_placeholders_before_execution():
    pool = FakePool()
    pool.connection.rows = [{"n": 7, "label": "seventy"}, {"n": 7, "label": "x"}]
    database = Database(pool)

    rows = run(
        database.fetch(
            "select $1::int as n, '%' || $2 as label", 7, "x"
        )
    )

    assert rows == [{"n": 7, "label": "seventy"}, {"n": 7, "label": "x"}]
    assert pool.acquire_count == 1
    assert pool.connection.calls == [
        ("select %s::int as n, '%%' || %s as label", (7, "x"))
    ]


def test_fetch_passes_no_parameters_for_parameterless_sql():
    pool = FakePool()
    pool.connection.rows = [{"one": 1}]

    rows = run(Database(pool).fetch("select 1 as one"))

    assert rows == [{"one": 1}]
    assert pool.connection.calls == [("select 1 as one", None)]


def test_fetchrow_returns_one_row_or_none():
    pool = FakePool()
    database = Database(pool)

    pool.connection.rows = [{"id": 1}, {"id": 2}]
    assert run(database.fetchrow("select * from t where id = $1", 1)) == {
        "id": 1
    }

    pool.connection.rows = []
    assert run(database.fetchrow("select * from t where id = $1", 2)) is None


def test_execute_returns_the_psycopg_status_tag():
    pool = FakePool()
    database = Database(pool)

    status = run(
        database.execute(
            "update media_assets set last_accessed_at = now() "
            "where id = $1 and last_accessed_at <= $2",
            uuid4(),
            "2026-01-01",
        )
    )

    assert status == "UPDATE 1"
    assert pool.connection.calls[0][1] is not None


def test_touch_accessed_counts_rows_from_the_status_tag():
    """The real service parses the status tag the adapter returns."""
    asset_id = uuid4()
    pool = FakePool()
    database = Database(pool)

    pool.connection.status = "UPDATE 1"
    assert run(assets.touch_accessed(database, asset_id)) is True
    assert pool.connection.calls[0][0].count("%s") == 2

    pool.connection.status = "UPDATE 0"
    assert run(assets.touch_accessed(database, asset_id)) is False


def test_fetch_times_out_and_discards_the_connection():
    pool = FakePool()
    pool.connection.delay = 5.0
    database = Database(pool)

    with pytest.raises(TimeoutError):
        run(database.fetch("select 1", timeout=0.01))

    assert pool.connection.closed is True


def test_transaction_commits_on_success():
    pool = FakePool()
    database = Database(pool)

    async def work() -> Any:
        async with database.transaction() as connection:
            return await connection.fetch("select $1::int as n", 1)

    result = run(work())

    assert result == []
    assert pool.log == ["begin", "commit"]
    assert pool.connection.calls == [("select %s::int as n", (1,))]


def test_transaction_rolls_back_on_error():
    pool = FakePool()
    database = Database(pool)

    async def work() -> None:
        async with database.transaction() as connection:
            await connection.execute(
                "update jobs set status = $1", "failed"
            )
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run(work())

    assert pool.log == ["begin", "rollback"]


def test_database_errors_are_propagated_unchanged():
    pool = FakePool()
    error = db_module.psycopg.errors.UniqueViolation("duplicate key")
    pool.connection.error = error
    database = Database(pool)

    with pytest.raises(db_module.psycopg.errors.UniqueViolation):
        run(database.execute("insert into t values ($1)", 1))

    assert is_unique_violation(error) is True


def test_close_closes_pool():
    pool = FakePool()

    run(Database(pool).close())

    assert pool.closed is True


def test_database_requires_a_pool():
    with pytest.raises(ConfigError):
        Database(None)


def test_database_schema_defaults_to_public():
    database = Database(FakePool())

    assert database.schema == "public"
    assert database.schema_sql == '"public"'


def test_database_schema_is_validated_and_quoted():
    database = Database(FakePool(), "vidfetch")

    assert database.schema == "vidfetch"
    assert database.schema_sql == '"vidfetch"'


@pytest.mark.parametrize("schema", ["pg_catalog", "auth", "Bad", "vid-fetch"])
def test_database_rejects_invalid_schema(schema):
    with pytest.raises(ConfigError):
        Database(FakePool(), schema)


# ---------------------------------------------------------------------------
# Driver exception taxonomy
# ---------------------------------------------------------------------------


def test_db_error_tuples_cover_driver_and_pool_failures():
    import psycopg
    from psycopg_pool import PoolClosed, PoolTimeout

    for error in (
        psycopg.OperationalError("down"),
        psycopg.errors.UniqueViolation("duplicate"),
        PoolTimeout("exhausted"),
        PoolClosed("closed"),
        OSError("socket"),
    ):
        assert isinstance(error, DB_ERRORS)
        assert isinstance(error, DB_UNAVAILABLE)


def test_unique_violation_helper_only_matches_unique_constraints():
    import psycopg

    assert is_unique_violation(psycopg.errors.UniqueViolation("dup")) is True
    assert is_unique_violation(psycopg.errors.ForeignKeyViolation("fk")) is False
    assert is_unique_violation(ValueError("nope")) is False


# ---------------------------------------------------------------------------
# Pool creation
# ---------------------------------------------------------------------------


class FakeAsyncConnectionPool:
    """Stand-in for ``psycopg_pool.AsyncConnectionPool``."""

    instances: list["FakeAsyncConnectionPool"] = []
    wait_error: BaseException | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.opened = False
        self.waited = False
        self.closed = False
        FakeAsyncConnectionPool.instances.append(self)

    async def open(self) -> None:
        self.opened = True

    async def wait(self) -> None:
        self.waited = True
        if FakeAsyncConnectionPool.wait_error is not None:
            raise FakeAsyncConnectionPool.wait_error

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pool_class(monkeypatch):
    FakeAsyncConnectionPool.instances = []
    FakeAsyncConnectionPool.wait_error = None
    monkeypatch.setattr(
        db_module, "AsyncConnectionPool", FakeAsyncConnectionPool
    )
    return FakeAsyncConnectionPool


def _settings(**env: str) -> Settings:
    values = {
        "DATABASE_URL": "postgresql://user:pass@pooler.example.test:6543/postgres"
    }
    values.update(env)
    return Settings.from_env(values)


def test_create_pool_requires_database_url():
    with pytest.raises(ConfigError):
        run(db_module.create_pool(Settings.from_env({})))


def test_create_pool_rejects_invalid_schema_before_connecting(
    monkeypatch, fake_pool_class
):
    called = False

    def fake_pool(**kwargs: Any) -> FakeAsyncConnectionPool:
        nonlocal called
        called = True
        return FakeAsyncConnectionPool(**kwargs)

    monkeypatch.setattr(db_module, "AsyncConnectionPool", fake_pool)

    with pytest.raises(ConfigError):
        run(db_module.create_pool(_settings(DB_SCHEMA="information_schema")))

    assert called is False


def test_create_pool_opens_and_waits_with_pooler_safe_options(
    fake_pool_class,
):
    settings = _settings()

    database = run(db_module.create_pool(settings, min_size=1, max_size=4))

    (pool,) = FakeAsyncConnectionPool.instances
    assert pool.kwargs["conninfo"] == settings.database_url
    assert pool.kwargs["min_size"] == 1
    assert pool.kwargs["max_size"] == 4
    assert pool.kwargs["open"] is False
    assert pool.kwargs["kwargs"]["row_factory"] is dict_row
    assert pool.kwargs["kwargs"]["autocommit"] is True
    assert pool.kwargs["kwargs"]["prepare_threshold"] is None
    assert "statement_cache_size" not in pool.kwargs
    assert pool.opened is True
    assert pool.waited is True
    assert database.pool is pool
    assert database.schema == "public"


def test_create_pool_closes_the_pool_when_wait_fails(fake_pool_class):
    FakeAsyncConnectionPool.wait_error = db_module.PoolTimeout("no server")

    with pytest.raises(db_module.PoolTimeout):
        run(db_module.create_pool(_settings()))

    (pool,) = FakeAsyncConnectionPool.instances
    assert pool.opened is True
    assert pool.closed is True


def test_create_pool_passes_configured_schema(fake_pool_class):
    database = run(db_module.create_pool(_settings(DB_SCHEMA="vidfetch")))

    assert database.schema == "vidfetch"
    assert database.schema_sql == '"vidfetch"'
