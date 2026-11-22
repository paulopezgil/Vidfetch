"""Per-user library visibility and download history.

The library is a *view* over ready jobs whose asset is still ready. Removing an
item sets ``download_jobs.library_hidden``; it never deletes the shared
``media_assets`` row or the job, so the download remains in history and other
users keep their access to the cached file.

History is deliberately unfiltered: it delegates to :func:`jobs.list_jobs` and
therefore keeps hidden library entries visible.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from ..core.db import Database
from . import jobs

MAX_PAGE_SIZE = 200

LIBRARY_COLUMNS = (
    "j.id as job_id, j.asset_id, "
    "coalesce(nullif(j.title, ''), a.title) as title, "
    "a.file_size_bytes, a.output_ext, a.thumbnail_path, j.created_at, "
    "j.status, j.format_selector, j.playlist_id"
)

# Every branch shares the same ownership/visibility predicate. Keeping it in
# one place makes it hard to accidentally drop a condition from the count or
# the page query. The FROM clause is a function because the schema is
# configurable per deployment.
def _library_from(schema_sql: str) -> str:
    return (
        f"from {schema_sql}.download_jobs j "
        f"join {schema_sql}.media_assets a on j.asset_id = a.id"
    )


LIBRARY_WHERE = (
    "where j.user_id = $1 "
    "and j.status = 'ready' "
    "and j.library_hidden = false "
    "and a.status = 'ready'"
)


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid user id.") from exc


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


async def list_library(
    db: Database,
    user_id: str | UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's visible library, newest first."""
    owner = _as_uuid(user_id)
    limit, offset = _clamp(limit, offset)

    library_from = _library_from(db.schema_sql)

    total_row = await db.fetchrow(
        f"select count(*) as total {library_from} {LIBRARY_WHERE}",
        owner,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {LIBRARY_COLUMNS} {library_from} {LIBRARY_WHERE} "
        f"order by j.created_at desc, j.id desc "
        f"limit $2 offset $3",
        owner,
        limit,
        offset,
    )
    return [dict(row) for row in rows], total


async def hide_library_item(
    db: Database,
    user_id: str | UUID,
    job_id: str | UUID,
) -> bool:
    """Hide one of the caller's ready jobs from their library.

    Returns ``True`` when a ready job owned by the caller matched. The asset and
    the job row are left in place.
    """
    owner = _as_uuid(user_id)
    identifier = _as_uuid(job_id)
    record = await db.fetchrow(
        f"update {db.schema_sql}.download_jobs "
        "set library_hidden = true, updated_at = now() "
        "where id = $1 and user_id = $2 and status = 'ready' "
        "returning id",
        identifier,
        owner,
    )
    return record is not None


async def list_history(
    db: Database,
    user_id: str | UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return the caller's job history, including hidden library entries."""
    return await jobs.list_jobs(
        db,
        user_id,
        status=status,
        limit=limit,
        offset=offset,
    )
