"""Async PostgreSQL access for the v2 backend.

The service layer is written against an asyncpg-style API: ``fetch``,
``fetchrow``, ``execute``, ``transaction`` and ``$1``-style placeholders. Since
v2.4 the driver underneath is psycopg 3; :class:`Connection` adapts a psycopg
connection to that shape (translating placeholders on the way in), so the
queries themselves did not have to change.

Connections run in autocommit mode (one statement commits immediately, as it
did under asyncpg) and return ``dict`` rows. Automatic statement preparation is
disabled: Postgres may sit behind a PgBouncer/Supavisor pooler in transaction
mode, where server-side prepared statements are not safe across requests.

Nothing here connects at import time. :func:`create_pool` is awaited during the
application lifespan; tests can construct :class:`Database` around any pool-like
object (including a fake) without a network.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager, AsyncIterator, Awaitable, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolClosed, PoolTimeout

from .config import (
    DEFAULT_DB_SCHEMA,
    ConfigError,
    Settings,
    validate_schema_name,
)

# Every failure that means "the database layer did not answer": a rejected
# statement (``psycopg.Error`` and its subclasses), an exhausted or closed pool,
# or a broken socket.
DB_ERRORS: tuple[type[BaseException], ...] = (
    psycopg.Error,
    PoolTimeout,
    PoolClosed,
    OSError,
)

# The projection routes map to a 503 "try again later". Every database failure
# reaches the user the same way, so today it is the full tuple above.
DB_UNAVAILABLE = DB_ERRORS


def is_unique_violation(exc: BaseException) -> bool:
    """Return True when ``exc`` is a unique-constraint violation (SQLSTATE 23505)."""
    return isinstance(exc, psycopg.errors.UniqueViolation)


_PLACEHOLDER = re.compile(r"\$(\d+)")


def adapt_placeholders(
    query: str, args: Sequence[Any]
) -> tuple[str, tuple[Any, ...]]:
    """Rewrite asyncpg-style ``$n`` placeholders for psycopg.

    psycopg binds positional parameters as ``%s`` and treats a bare ``%`` in the
    statement as the start of a placeholder, so:

    * with no arguments the query is returned unchanged (psycopg performs no
      percent interpolation for parameterless statements);
    * otherwise literal ``%`` characters are doubled first, then every ``$n``
      becomes ``%s`` and appends ``args[n - 1]`` to the parameter tuple.

    Arguments are appended in occurrence order, so a repeated reference such as
    ``$1 = $1`` yields the same value twice. Gaps (``$1`` and ``$3``) are
    allowed and unreferenced arguments are ignored. A placeholder that is not a
    valid index into ``args`` raises :class:`ValueError` before any statement is
    sent.
    """
    if not args:
        return query, ()

    params: list[Any] = []

    def _replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if not 1 <= index <= len(args):
            raise ValueError(
                f"Query references ${index} but {len(args)} "
                "argument(s) were supplied."
            )
        params.append(args[index - 1])
        return "%s"

    # Escape first: the replacement inserted by ``_replace`` must stay a real
    # ``%s`` placeholder rather than becoming ``%%s``.
    sql = _PLACEHOLDER.sub(_replace, query.replace("%", "%%"))
    return sql, tuple(params)


class Connection:
    """asyncpg-shaped facade over a psycopg async connection.

    Service code receives this object from :meth:`Database.acquire` and from
    :meth:`Database.transaction`, then calls ``fetch``/``fetchrow``/``execute``
    with ``$n`` placeholders exactly as before.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @property
    def raw(self) -> Any:
        """The underlying psycopg connection (``transaction()`` lives here)."""
        return self._connection

    async def _run(
        self, operation: Awaitable[Any], timeout: float | None
    ) -> Any:
        if timeout is None:
            return await operation
        try:
            async with asyncio.timeout(timeout):
                return await operation
        except TimeoutError:
            # The server may still be working on a cancelled statement, so the
            # connection is not reusable. Close it and let the pool replace it.
            # Closing is best effort: a broken socket must not mask the timeout
            # with a different exception.
            try:
                await self._connection.close()
            except Exception:  # noqa: BLE001 - the timeout is the real error
                pass
            raise

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[Any]:
        sql, params = adapt_placeholders(query, args)

        async def operation() -> list[Any]:
            async with self._connection.cursor() as cursor:
                await cursor.execute(sql, params or None)
                return list(await cursor.fetchall())

        return await self._run(operation(), timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> Any:
        sql, params = adapt_placeholders(query, args)

        async def operation() -> Any:
            async with self._connection.cursor() as cursor:
                await cursor.execute(sql, params or None)
                return await cursor.fetchone()

        return await self._run(operation(), timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        sql, params = adapt_placeholders(query, args)

        async def operation() -> str:
            async with self._connection.cursor() as cursor:
                await cursor.execute(sql, params or None)
                # e.g. "UPDATE 1": callers count affected rows from this tag.
                return cursor.statusmessage or ""

        return await self._run(operation(), timeout)

    def transaction(self) -> AsyncContextManager[Any]:
        """Start a transaction on this connection (psycopg handles autocommit)."""
        return self._connection.transaction()

    async def close(self) -> None:
        await self._connection.close()


class Database:
    """Thin async wrapper around a psycopg connection pool.

    The wrapper acquires a connection per operation so concurrent requests do
    not share a mutable connection. Multi-statement work uses
    :meth:`transaction`, which pins one connection for the duration.

    ``schema`` is the application schema that owns every table the app reads or
    writes. ``schema_sql`` is the same name, safely quoted, for interpolation
    into SQL. Values are validated before they reach either property, so they
    are never caller-supplied SQL.
    """

    def __init__(self, pool: Any, schema: str = DEFAULT_DB_SCHEMA) -> None:
        if pool is None:
            raise ConfigError("A database pool is required.")
        self._pool = pool
        self._schema = validate_schema_name(schema)

    @property
    def pool(self) -> Any:
        return self._pool

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def schema_sql(self) -> str:
        """Return the schema as a quoted SQL identifier (``'"vidfetch"'``)."""
        return f'"{self._schema}"'

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Connection]:
        # psycopg pools expose ``connection()`` as the async context manager
        # that checks a connection out and returns it on exit. (asyncpg's
        # ``acquire()`` does not exist here.)
        async with self._pool.connection() as connection:
            yield Connection(connection)

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[Any]:
        async with self.acquire() as connection:
            return await connection.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> Any:
        async with self.acquire() as connection:
            return await connection.fetchrow(query, *args, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        async with self.acquire() as connection:
            return await connection.execute(query, *args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Yield a connection inside a database transaction.

        Commits on normal exit and rolls back when the body raises.
        """
        async with self.acquire() as connection:
            async with connection.transaction():
                yield connection

    async def close(self) -> None:
        await self._pool.close()


async def create_pool(
    settings: Settings,
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> Database:
    """Create the application's psycopg connection pool.

    The pool is intentionally small: v2 runs as a single backend process, and
    the Postgres pooler already multiplexes client connections. The pool is
    created closed, then opened and primed explicitly so a bad ``DATABASE_URL``
    fails during startup rather than on the first request. Await this during
    startup only, never at import time.
    """
    if not settings.database_url:
        raise ConfigError("DATABASE_URL is not configured.")

    # Reject a bad schema before opening a connection. ``Database`` validates
    # again, but doing it here means a misconfigured deployment never touches
    # the database at all.
    schema = validate_schema_name(settings.db_schema)

    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={
            "row_factory": dict_row,
            # asyncpg-style single-statement semantics: no implicit open
            # transaction is left behind when a service calls ``execute``.
            "autocommit": True,
            # Keep every statement unprepared; required behind a
            # transaction-mode pooler.
            "prepare_threshold": None,
        },
    )
    try:
        await pool.open()
        await pool.wait()
    except BaseException:
        # Never leak a half-open pool (its background workers included).
        await pool.close()
        raise
    return Database(pool, schema)
