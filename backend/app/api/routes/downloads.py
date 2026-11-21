"""User-scoped metadata, download, and job endpoints.

Every route requires an authenticated, approved user and only ever exposes the
caller's own jobs. Another user's job is reported as 404, never 403, so its
existence is not leaked. Admin-wide job views are deliberately absent from this
router.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ...core.config import Settings
from ...core.db import Database
from ...models.schemas import (
    DownloadJobList,
    DownloadJobOut,
    DownloadRequest,
    InfoOut,
    InfoRequest,
    JobStatus,
    ProfileOut,
)
from ...services import jobs, ytdlp
from ...services.options import options_hash
from ..deps import get_db, get_settings, require_approved
from ..errors import ApiError

router = APIRouter(tags=["downloads"])

_DB_UNAVAILABLE = (asyncpg.PostgresError, OSError, ConnectionError)
_TERMINAL = frozenset({"ready", "failed", "cancelled"})


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "job_not_found", "Download job not found.")


@router.post("/api/info", response_model=InfoOut)
async def resolve_info(
    payload: InfoRequest,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
) -> InfoOut:
    """Resolve video or playlist metadata without downloading."""
    try:
        info = await run_in_threadpool(ytdlp.get_info, payload.url, settings)
    except ytdlp.DownloadError as exc:
        raise ApiError(400, exc.code, exc.message) from exc
    try:
        return InfoOut.model_validate(info)
    except ValidationError as exc:
        raise ApiError(
            500,
            "info_failed",
            "The site returned metadata that could not be understood.",
        ) from exc


@router.post("/api/downloads", response_model=DownloadJobOut)
async def create_download(
    payload: DownloadRequest,
    idempotency_header: str | None = Header(
        default=None, alias="Idempotency-Key"
    ),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> DownloadJobOut:
    """Queue a single-video download, idempotent on the client's key."""
    if db is None:
        raise _unavailable()
    if payload.kind == "playlist":
        raise ApiError(
            501,
            "playlist_not_implemented",
            "Playlist downloads are not available yet.",
        )
    if payload.playlist_id is not None:
        raise ApiError(
            400,
            "invalid_request",
            "playlist_id is only valid for playlist downloads.",
        )

    key = (idempotency_header or payload.idempotency_key or "").strip() or None
    if key is not None and len(key) > 200:
        raise ApiError(400, "invalid_request", "The idempotency key is too long.")

    selector = ytdlp.encode_intent(payload.format, payload.embed_subs)
    digest = options_hash(
        payload.format, payload.embed_subs, extra={"kind": payload.kind}
    )
    try:
        row = await jobs.create_job(
            db,
            user_id=profile.id,
            kind="video",
            source_url=payload.url,
            title="",
            options_hash=digest,
            format_selector=selector,
            idempotency_key=key,
        )
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Invalid download request.") from exc
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return DownloadJobOut.model_validate(row)


@router.get("/api/downloads", response_model=DownloadJobList)
async def list_downloads(
    status: JobStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> DownloadJobList:
    """List the caller's jobs, newest first."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await jobs.list_jobs(
            db,
            profile.id,
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Invalid job filter.") from exc
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return DownloadJobList(
        items=[DownloadJobOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/downloads/{job_id}", response_model=DownloadJobOut)
async def get_download(
    job_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> DownloadJobOut:
    """Return one of the caller's jobs; 404 for anyone else's."""
    if db is None:
        raise _unavailable()
    try:
        row = await jobs.get_job(db, job_id, user_id=profile.id)
    except ValueError as exc:
        raise _not_found() from exc
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    return DownloadJobOut.model_validate(row)


@router.post("/api/downloads/{job_id}/cancel", response_model=DownloadJobOut)
async def cancel_download(
    job_id: UUID,
    request: Request,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> DownloadJobOut:
    """Request cancellation of one of the caller's jobs."""
    if db is None:
        raise _unavailable()
    try:
        row = await jobs.get_job(db, job_id, user_id=profile.id)
    except ValueError as exc:
        raise _not_found() from exc
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    if row.get("status") in _TERMINAL:
        return DownloadJobOut.model_validate(row)

    worker: Any = getattr(request.app.state, "worker", None)
    try:
        if worker is not None:
            await worker.request_cancel(job_id)
        else:
            row = await jobs.request_cancel(db, job_id) or row
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc

    try:
        refreshed = await jobs.get_job(db, job_id, user_id=profile.id)
    except _DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return DownloadJobOut.model_validate(refreshed or row)
