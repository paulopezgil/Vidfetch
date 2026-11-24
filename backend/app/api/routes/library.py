"""Owner-scoped library and download-history endpoints.

Library removal only hides the caller's job; it never deletes a shared media
asset. History intentionally keeps hidden library entries visible.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import (
    DownloadJobList,
    DownloadJobOut,
    JobStatus,
    LibraryList,
    LibraryItemOut,
    ProfileOut,
)
from ...services import library
from ..deps import get_db, require_approved
from ..errors import ApiError

router = APIRouter(tags=["library"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "job_not_found", "Library item not found.")


@router.get("/api/library", response_model=LibraryList)
async def list_library(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> LibraryList:
    """List the caller's visible ready assets, newest first."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await library.list_library(
            db, profile.id, limit=limit, offset=offset
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return LibraryList(
        items=[LibraryItemOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/api/library/{job_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def hide_library_item(
    job_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> Response:
    """Remove one of the caller's ready jobs from their library."""
    if db is None:
        raise _unavailable()
    try:
        hidden = await library.hide_library_item(db, profile.id, job_id)
    except ValueError as exc:
        raise _not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not hidden:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/history", response_model=DownloadJobList)
async def list_history(
    status: JobStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> DownloadJobList:
    """List the caller's full job history, including hidden library entries."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await library.list_history(
            db,
            profile.id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Invalid job filter.") from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return DownloadJobList(
        items=[DownloadJobOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
