"""Per-user track metadata over the shared media cache.

A ``user_tracks`` row is the caller's own library entry for a shared
``media_assets`` file. The row is created from ready download jobs (by the
database trigger), so a track is only visible while the user still has a ready,
non-hidden job for that asset and the asset itself is ready.

The library rules are preserved rather than duplicated: the visibility
predicate lives in the shared lateral join and ``where`` clause below, and a
track disappears as soon as the user hides their only ready job or the shared
asset is no longer ready.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from ..core.db import Database

MAX_PAGE_SIZE = 200

TRACKS_COLUMNS = (
    "ut.id, ut.asset_id, j.id as job_id, a.canonical_id, "
    "coalesce(nullif(ut.custom_title, ''), nullif(j.title, ''), a.title, '') "
    "as title, "
    "ut.custom_artist as artist, ut.custom_album as album, "
    "ut.cover_path, a.thumbnail_path, a.duration_seconds, a.file_size_bytes, "
    "a.output_ext, j.format_selector, j.playlist_id, "
    "ut.downloaded_at, ut.updated_at"
)


# Every branch shares the same ownership/visibility predicate. The lateral join
# picks exactly one representative ready job per (user, asset); because it is an
# inner join, a track with no eligible job is excluded. The FROM clause is a
# function because the schema is configurable per deployment.
def _tracks_from(schema_sql: str) -> str:
    return (
        f"from {schema_sql}.user_tracks ut "
        f"join {schema_sql}.media_assets a on a.id = ut.asset_id "
        f"join lateral ("
        f"select j.id, j.title, j.format_selector, j.playlist_id "
        f"from {schema_sql}.download_jobs j "
        f"where j.user_id = ut.user_id "
        f"and j.asset_id = ut.asset_id "
        f"and j.status = 'ready' "
        f"and j.library_hidden = false "
        f"order by j.completed_at desc nulls last, "
        f"j.created_at desc, j.id desc "
        f"limit 1"
        f") j on true"
    )


TRACKS_WHERE = "where ut.user_id = $1 and ut.deleted_at is null and a.status = 'ready'"


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid user id.") from exc


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


async def list_tracks(
    db: Database,
    user_id: str | UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's visible tracks, newest first."""
    owner = _as_uuid(user_id)
    limit, offset = _clamp(limit, offset)

    tracks_from = _tracks_from(db.schema_sql)

    total_row = await db.fetchrow(
        f"select count(*) as total {tracks_from} {TRACKS_WHERE}",
        owner,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {TRACKS_COLUMNS} {tracks_from} {TRACKS_WHERE} "
        f"order by ut.downloaded_at desc, ut.id desc "
        f"limit $2 offset $3",
        owner,
        limit,
        offset,
    )
    return [dict(row) for row in rows], total
