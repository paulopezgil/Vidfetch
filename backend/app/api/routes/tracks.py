"""Owner-scoped track listing.

Tracks are per-user rows over the shared media cache. The router only exposes
reads; rows are created by the database trigger when a download becomes ready.
"""
from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from ...core.db import Database
from ...models.schemas import ProfileOut, TrackList, TrackOut
from ...services import tracks
from ..deps import get_db, require_approved
from ..errors import ApiError

router = APIRouter(tags=["tracks"])

_DB_UNAVAILABLE = (asyncpg.PostgresError, OSError, ConnectionError)


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


@router.get("/api/tracks", response_model=TrackList)
async def list_tracks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> TrackList:
    """List the caller's visible tracks, newest downloaded first."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await tracks.list_tracks(
            db, profile.id, limit=limit, offset=offset, q=q
        )
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return TrackList(
        items=[TrackOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
