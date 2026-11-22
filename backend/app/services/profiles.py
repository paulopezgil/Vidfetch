"""Profile, approval, and admin-audit queries.

All SQL uses asyncpg positional placeholders (``$1``, ``$2``, ...) and passes
values as parameters; user input is never interpolated into a statement. The
admin mutations run inside a transaction that also records an audit entry, so a
partial update can never be committed.

Guards prevent the last approved administrator from being revoked or demoted.
The guards lock the set of approved admins before changing anything, which
serializes concurrent admin mutations and avoids a race where two admins demote
each other and leave the deployment with none.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..core.db import Database

MAX_PAGE_SIZE = 200

# Columns returned to the API. ``approved_at``/``approved_by`` are read so
# callers (and future response models) can display the approval trail.
_PROFILE_COLUMNS = (
    "id, email, is_approved, app_role, approved_at, approved_by, "
    "created_at, updated_at"
)

# Whitelisted sort keys. A request value is only ever used as a dictionary key;
# the emitted SQL fragment comes from this table, never from the caller.
_SORT_COLUMNS: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "email": "lower(email)",
    "is_approved": "is_approved",
    "app_role": "app_role",
}


class ConflictError(Exception):
    """A domain conflict (for example, demoting the last administrator)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid user id.") from exc


def _row(record: Any) -> dict[str, Any] | None:
    return None if record is None else dict(record)


async def get_profile(db: Database, user_id: str | UUID) -> dict[str, Any] | None:
    """Return a single profile row, or ``None`` when it does not exist."""
    record = await db.fetchrow(
        f"select {_PROFILE_COLUMNS} from {db.schema_sql}.profiles where id = $1",
        _as_uuid(user_id),
    )
    return _row(record)


async def list_profiles(
    db: Database,
    *,
    search: str | None = None,
    approved: bool | None = None,
    role: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "created_at",
    order: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of profiles plus the total matching row count.

    ``limit`` is clamped to ``1..200`` and ``offset`` to ``>= 0``. ``search`` is
    a case-insensitive substring match on the email address. ``sort``/``order``
    are whitelisted rather than interpolated.
    """
    limit = max(1, min(MAX_PAGE_SIZE, int(limit)))
    offset = max(0, int(offset))

    conditions: list[str] = []
    args: list[Any] = []

    def placeholder(value: Any) -> str:
        args.append(value)
        return f"${len(args)}"

    if search is not None and search.strip():
        conditions.append(
            f"lower(email) like '%' || {placeholder(search.strip().lower())} || '%'"
        )
    if approved is not None:
        conditions.append(f"is_approved = {placeholder(bool(approved))}")
    if role is not None:
        conditions.append(f"app_role = {placeholder(str(role))}")

    where = f" where {' and '.join(conditions)}" if conditions else ""

    total_row = await db.fetchrow(
        f"select count(*) as total from {db.schema_sql}.profiles{where}", *args
    )
    total = int(total_row["total"]) if total_row is not None else 0

    sort_expression = _SORT_COLUMNS.get(str(sort), "created_at")
    direction = "asc" if str(order).strip().lower() == "asc" else "desc"

    limit_ph = placeholder(limit)
    offset_ph = placeholder(offset)
    rows = await db.fetch(
        f"select {_PROFILE_COLUMNS} from {db.schema_sql}.profiles{where} "
        f"order by {sort_expression} {direction}, id asc "
        f"limit {limit_ph} offset {offset_ph}",
        *args,
    )
    return [dict(row) for row in rows], total


async def approved_admin_ids(connection: Any, schema_sql: str) -> list[Any]:
    """Lock and return the ids of currently approved admins.

    ``FOR UPDATE`` serializes concurrent revoke/demote transactions so the
    last-admin guard cannot be bypassed by two simultaneous requests.
    ``schema_sql`` is the already-validated quoted schema from the caller's
    :class:`~backend.app.core.db.Database`.
    """
    rows = await connection.fetch(
        f"select id from {schema_sql}.profiles "
        "where app_role = 'admin' and is_approved = true "
        "for update"
    )
    return [row["id"] for row in rows]


async def _audit(
    connection: Any,
    schema_sql: str,
    actor_id: str | UUID,
    action: str,
    target_user_id: str | UUID,
    metadata: dict[str, Any] | None = None,
) -> None:
    await connection.execute(
        f"insert into {schema_sql}.admin_audit_log "
        "(actor_id, action, target_user_id, metadata) "
        "values ($1, $2, $3, $4::jsonb)",
        _as_uuid(actor_id),
        action,
        _as_uuid(target_user_id),
        json.dumps(metadata or {}, sort_keys=True),
    )


async def approve_profile(
    db: Database, user_id: str | UUID, actor_id: str | UUID
) -> dict[str, Any] | None:
    """Approve a profile and record the action. ``None`` means no such user."""
    target_id = _as_uuid(user_id)
    schema_sql = db.schema_sql
    async with db.transaction() as connection:
        record = await connection.fetchrow(
            f"update {schema_sql}.profiles "
            f"set is_approved = true, approved_at = now(), approved_by = $2, "
            f"updated_at = now() "
            f"where id = $1 "
            f"returning {_PROFILE_COLUMNS}",
            target_id,
            _as_uuid(actor_id),
        )
        if record is None:
            return None
        await _audit(
            connection,
            schema_sql,
            actor_id,
            "approve_profile",
            target_id,
            {"is_approved": True},
        )
        return dict(record)


async def revoke_profile(
    db: Database, user_id: str | UUID, actor_id: str | UUID
) -> dict[str, Any] | None:
    """Revoke approval, refusing to remove the last approved administrator."""
    target_id = _as_uuid(user_id)
    schema_sql = db.schema_sql
    async with db.transaction() as connection:
        admin_ids = await approved_admin_ids(connection, schema_sql)
        target = await connection.fetchrow(
            f"select {_PROFILE_COLUMNS} from {schema_sql}.profiles "
            f"where id = $1 for update",
            target_id,
        )
        if target is None:
            return None
        if (
            target["app_role"] == "admin"
            and bool(target["is_approved"])
            and len(admin_ids) <= 1
        ):
            raise ConflictError(
                "last_admin",
                "Cannot revoke the last approved administrator.",
            )

        record = await connection.fetchrow(
            f"update {schema_sql}.profiles "
            f"set is_approved = false, approved_at = null, approved_by = null, "
            f"updated_at = now() "
            f"where id = $1 "
            f"returning {_PROFILE_COLUMNS}",
            target_id,
        )
        if record is None:  # pragma: no cover - target was locked above
            return None
        await _audit(
            connection,
            schema_sql,
            actor_id,
            "revoke_profile",
            target_id,
            {"is_approved": False},
        )
        return dict(record)


async def set_profile_role(
    db: Database,
    user_id: str | UUID,
    app_role: str,
    actor_id: str | UUID,
) -> dict[str, Any] | None:
    """Change a profile's application role, keeping at least one admin."""
    if app_role not in ("user", "admin"):
        raise ValueError("Invalid application role.")
    target_id = _as_uuid(user_id)
    schema_sql = db.schema_sql
    async with db.transaction() as connection:
        admin_ids = await approved_admin_ids(connection, schema_sql)
        target = await connection.fetchrow(
            f"select {_PROFILE_COLUMNS} from {schema_sql}.profiles "
            f"where id = $1 for update",
            target_id,
        )
        if target is None:
            return None
        if (
            app_role != "admin"
            and target["app_role"] == "admin"
            and bool(target["is_approved"])
            and len(admin_ids) <= 1
        ):
            raise ConflictError(
                "last_admin",
                "Cannot demote the last approved administrator.",
            )

        record = await connection.fetchrow(
            f"update {schema_sql}.profiles set app_role = $2, updated_at = now() "
            f"where id = $1 "
            f"returning {_PROFILE_COLUMNS}",
            target_id,
            app_role,
        )
        if record is None:  # pragma: no cover - target was locked above
            return None
        await _audit(
            connection,
            schema_sql,
            actor_id,
            "set_profile_role",
            target_id,
            {"app_role": app_role},
        )
        return dict(record)


async def count_admins(db: Database) -> int:
    """Count currently approved administrators."""
    record = await db.fetchrow(
        f"select count(*) as total from {db.schema_sql}.profiles "
        "where app_role = 'admin' and is_approved = true"
    )
    return int(record["total"]) if record is not None else 0
