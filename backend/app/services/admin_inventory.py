"""Admin-wide job and media-asset inventory, plus guarded asset deletion.

These helpers are only reachable from ``/api/admin`` routes. They never trust a
caller-supplied column or status: filters are whitelisted and every value is
passed as a bound parameter.

Deleting an asset is refused while any non-terminal job still references it.
The shared file is removed on a best-effort basis *after* the row deletion and
only through the path-safe storage helper, so a corrupt relative path can never
escape the media root. Every successful deletion is recorded in
``admin_audit_log`` inside the same transaction.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..core.db import Database
from . import assets, jobs
from .profiles import ConflictError

MAX_PAGE_SIZE = 200

ASSET_STATUSES = frozenset({"processing", "ready", "failed"})

# A job in one of these states is still using the asset. Ready/failed/cancelled
# jobs are terminal and only hold a historical reference.
ACTIVE_JOB_STATUSES = ("queued", "resolving", "downloading", "processing")
_ACTIVE_STATUS_SQL = ", ".join(f"'{status}'" for status in ACTIVE_JOB_STATUSES)


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid identifier.") from exc


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


def _prefix_columns(columns: str, alias: str) -> str:
    """Qualify a comma-separated column list for a join."""
    return ", ".join(
        f"{alias}.{name.strip()}" for name in columns.split(",") if name.strip()
    )


# ``profiles`` and ``download_jobs`` both have ``id``/``created_at``, so every
# job column must be qualified in the admin join.
ADMIN_JOB_COLUMNS = (
    _prefix_columns(jobs.JOB_COLUMNS, "j")
    + ", coalesce(p.email, '') as user_email"
)

def _admin_asset_from(schema_sql: str) -> str:
    return f"from {schema_sql}.media_assets a where 1 = 1"


def _admin_asset_columns(schema_sql: str) -> str:
    return (
        _prefix_columns(assets.ASSET_COLUMNS, "a")
        + ", "
        + f"(select count(*) from {schema_sql}.download_jobs j "
        + "where j.asset_id = a.id) as job_count, "
        + f"(select count(distinct j.user_id) from {schema_sql}.download_jobs j "
        + "where j.asset_id = a.id) as user_count"
    )


async def list_jobs(
    db: Database,
    *,
    user_id: str | UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of all users' jobs, newest first.

    ``search`` matches the owner's email or the job title, case-insensitively.
    """
    if status is not None and status not in jobs.JOB_STATUSES:
        raise ValueError("Invalid job status.")
    owner = _as_uuid(user_id) if user_id is not None else None
    limit, offset = _clamp(limit, offset)

    conditions: list[str] = []
    args: list[Any] = []

    def placeholder(value: Any) -> str:
        args.append(value)
        return f"${len(args)}"

    if owner is not None:
        conditions.append(f"j.user_id = {placeholder(owner)}")
    if status is not None:
        conditions.append(f"j.status = {placeholder(status)}")
    if search is not None and search.strip():
        pattern = search.strip().lower()
        conditions.append(
            "(lower(p.email) like '%' || "
            f"{placeholder(pattern)} || '%' or lower(j.title) like '%' || "
            f"{placeholder(pattern)} || '%')"
        )

    where = f" where {' and '.join(conditions)}" if conditions else ""

    schema_sql = db.schema_sql
    total_row = await db.fetchrow(
        f"select count(*) as total from {schema_sql}.download_jobs j "
        f"join {schema_sql}.profiles p on p.id = j.user_id{where}",
        *args,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    limit_ph = placeholder(limit)
    offset_ph = placeholder(offset)
    rows = await db.fetch(
        f"select {ADMIN_JOB_COLUMNS} from {schema_sql}.download_jobs j "
        f"join {schema_sql}.profiles p on p.id = j.user_id{where} "
        f"order by j.created_at desc, j.id desc "
        f"limit {limit_ph} offset {offset_ph}",
        *args,
    )
    return [dict(row) for row in rows], total


async def list_assets(
    db: Database,
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the global asset cache, newest first.

    ``job_count`` and ``user_count`` describe how many download jobs (and
    distinct users) currently reference the asset.
    """
    if status is not None and status not in ASSET_STATUSES:
        raise ValueError("Invalid asset status.")
    limit, offset = _clamp(limit, offset)

    conditions: list[str] = []
    args: list[Any] = []

    def placeholder(value: Any) -> str:
        args.append(value)
        return f"${len(args)}"

    if status is not None:
        conditions.append(f"a.status = {placeholder(status)}")
    if search is not None and search.strip():
        pattern = search.strip().lower()
        conditions.append(
            "(lower(a.title) like '%' || "
            f"{placeholder(pattern)} || '%' or lower(a.canonical_id) like '%' || "
            f"{placeholder(pattern)} || '%')"
        )

    where = "".join(f" and {condition}" for condition in conditions)
    schema_sql = db.schema_sql
    admin_asset_from = _admin_asset_from(schema_sql)

    total_row = await db.fetchrow(
        f"select count(*) as total {admin_asset_from}{where}", *args
    )
    total = int(total_row["total"]) if total_row is not None else 0

    limit_ph = placeholder(limit)
    offset_ph = placeholder(offset)
    rows = await db.fetch(
        f"select {_admin_asset_columns(schema_sql)} {admin_asset_from}{where} "
        f"order by a.created_at desc, a.id desc "
        f"limit {limit_ph} offset {offset_ph}",
        *args,
    )
    return [dict(row) for row in rows], total


def _remove_file(storage: Any, relative: Any) -> bool:
    """Delete one stored file without ever letting a bad path escape the root."""
    if not isinstance(relative, str) or not relative.strip():
        return False
    try:
        return bool(storage.delete_asset_file(relative))
    except (AttributeError, OSError, ValueError):
        # Best effort: a missing/unsafe file must not block the row deletion.
        return False


def _remove_asset_files(storage: Any, asset: dict[str, Any]) -> None:
    seen: set[str] = set()
    for key in ("file_path", "thumbnail_path"):
        relative = asset.get(key)
        if isinstance(relative, str) and relative and relative not in seen:
            seen.add(relative)
            _remove_file(storage, relative)


async def delete_asset(
    db: Database,
    storage: Any,
    asset_id: str | UUID,
    actor_id: str | UUID,
) -> dict[str, Any] | None:
    """Delete a global asset and its file, or return ``None`` if it is gone.

    Raises :class:`ConflictError` with code ``asset_in_use`` while any
    non-terminal job still references the asset. Jobs that referenced the
    deleted row have their ``asset_id`` cleared by the database's
    ``on delete set null`` foreign key.
    """
    identifier = _as_uuid(asset_id)
    actor = _as_uuid(actor_id)
    schema_sql = db.schema_sql

    async with db.transaction() as connection:
        record = await connection.fetchrow(
            f"select {assets.ASSET_COLUMNS} from {schema_sql}.media_assets "
            f"where id = $1 for update",
            identifier,
        )
        if record is None:
            return None
        asset = dict(record)

        active = await connection.fetchrow(
            f"select count(*) as total from {schema_sql}.download_jobs "
            f"where asset_id = $1 and status in ({_ACTIVE_STATUS_SQL})",
            identifier,
        )
        if active is not None and int(active["total"]) > 0:
            raise ConflictError(
                "asset_in_use",
                "This asset is still in use by an active download.",
            )

        deleted = await connection.fetchrow(
            f"delete from {schema_sql}.media_assets where id = $1 "
            f"returning {assets.ASSET_COLUMNS}",
            identifier,
        )
        if deleted is None:  # pragma: no cover - the row was locked above
            return None
        deleted_row = dict(deleted)

        await connection.execute(
            f"insert into {schema_sql}.admin_audit_log "
            "(actor_id, action, metadata) "
            "values ($1, $2, $3::jsonb)",
            actor,
            "delete_asset",
            json.dumps(
                {
                    "asset_id": str(identifier),
                    "canonical_id": str(asset.get("canonical_id") or ""),
                },
                sort_keys=True,
            ),
        )

    # Remove files only after the row deletion and audit insert committed. A
    # failed transaction must not leave a live database row pointing at a file
    # that was already unlinked.
    _remove_asset_files(storage, asset)
    return deleted_row
