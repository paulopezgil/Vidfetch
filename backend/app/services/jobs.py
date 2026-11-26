"""Durable per-user download queue and history.

Every query is scoped by ``user_id`` unless the caller is an admin endpoint
(those live in a separate router). Job updates go through a column whitelist so
a caller can never smuggle an arbitrary column (or SQL) into an ``update``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ..core.db import DB_ERRORS, Database, is_unique_violation

MAX_PAGE_SIZE = 200

JOB_COLUMNS = (
    "id, user_id, asset_id, playlist_id, kind, source_url, title, options_hash, "
    "format_selector, artist, album, idempotency_key, status, progress, "
    "downloaded_bytes, total_bytes, speed, eta_seconds, error, attempts, "
    "created_at, updated_at, started_at, completed_at, cancel_requested, "
    "item_index, item_count, current_item_title, current_item_progress"
)

JOB_STATUSES = frozenset(
    {
        "queued",
        "resolving",
        "downloading",
        "processing",
        "ready",
        "failed",
        "cancelled",
    }
)

JOB_KINDS = frozenset({"video", "playlist", "playlist_item"})

# Playlist items are recorded per item and are never queued for the dispatcher.
PLAYLIST_ITEM_TERMINAL_STATUSES = frozenset({"ready", "failed"})

# Columns a caller may update. ``id``, ``user_id``, ``created_at``, and
# ``options_hash`` are deliberately not updatable.
UPDATABLE_COLUMNS = frozenset(
    {
        "asset_id",
        "playlist_id",
        "kind",
        "source_url",
        "title",
        "format_selector",
        "artist",
        "album",
        "idempotency_key",
        "status",
        "progress",
        "downloaded_bytes",
        "total_bytes",
        "speed",
        "eta_seconds",
        "error",
        "attempts",
        "started_at",
        "completed_at",
        "cancel_requested",
        "item_index",
        "item_count",
        "current_item_title",
        "current_item_progress",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid job id.") from exc


def _row(record: Any) -> dict[str, Any] | None:
    return None if record is None else dict(record)


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


async def create_job(
    db: Database,
    *,
    user_id: str | UUID,
    kind: str = "video",
    source_url: str,
    title: str = "",
    options_hash: str,
    format_selector: str = "",
    idempotency_key: str | None = None,
    playlist_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Insert a queued job, or return the existing job for an idempotency key."""
    if kind not in JOB_KINDS:
        raise ValueError("Invalid job kind.")
    if not options_hash or not options_hash.strip():
        raise ValueError("options_hash is required.")
    owner = _as_uuid(user_id)
    playlist = _as_uuid(playlist_id) if playlist_id is not None else None
    key = (idempotency_key or "").strip() or None
    if key is not None and len(key) > 200:
        raise ValueError("Idempotency key is too long.")

    if key is not None:
        existing = await db.fetchrow(
            f"select {JOB_COLUMNS} from {db.schema_sql}.download_jobs "
            f"where user_id = $1 and idempotency_key = $2",
            owner,
            key,
        )
        if existing is not None:
            return dict(existing)

    try:
        record = await db.fetchrow(
            f"insert into {db.schema_sql}.download_jobs "
            f"(user_id, kind, source_url, title, options_hash, format_selector, "
            f"idempotency_key, playlist_id) "
            f"values ($1, $2, $3, $4, $5, $6, $7, $8) "
            f"returning {JOB_COLUMNS}",
            owner,
            kind,
            (source_url or "")[:2048],
            (title or "")[:500],
            options_hash,
            format_selector or "",
            key,
            playlist,
        )
    except DB_ERRORS as exc:
        if not is_unique_violation(exc):
            raise
        # A concurrent request won the idempotency race; return its job.
        if key is not None:
            existing = await db.fetchrow(
                f"select {JOB_COLUMNS} from {db.schema_sql}.download_jobs "
                f"where user_id = $1 and idempotency_key = $2",
                owner,
                key,
            )
            if existing is not None:
                return dict(existing)
        raise
    if record is None:  # pragma: no cover - INSERT ... RETURNING always returns
        raise RuntimeError("Job insert returned no row.")
    return dict(record)


async def record_playlist_item_job(
    db: Database,
    *,
    user_id: str | UUID,
    playlist_id: str | UUID,
    source_url: str,
    title: str,
    options_hash: str,
    format_selector: str = "",
    status: str,
    asset_id: str | UUID | None = None,
    error: str = "",
    artist: str = "",
    album: str = "",
    item_index: int = 0,
    item_count: int = 0,
    job_id: str | UUID | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record one finished playlist item as a terminal ``playlist_item`` job.

    The dispatcher only claims ``queued`` jobs, so these rows are inserted in a
    terminal state and can never be picked up again. Passing ``job_id`` updates
    that job when it is a ``playlist_item`` job owned by the same user and
    playlist (a re-run of an already-downloaded playlist), otherwise a new job
    row is inserted.
    """
    candidate = str(status or "").strip()
    if candidate not in PLAYLIST_ITEM_TERMINAL_STATUSES:
        raise ValueError("Playlist item job status must be ready or failed.")
    if not isinstance(options_hash, str) or not options_hash.strip():
        raise ValueError("options_hash is required.")

    owner = _as_uuid(user_id)
    playlist = _as_uuid(playlist_id)
    asset = _as_uuid(asset_id) if asset_id is not None else None
    if candidate == "failed":
        # A failed item never owns media, so it can never seed a track.
        asset = None
    identifier = _as_uuid(job_id) if job_id is not None else None
    finished = completed_at or _now()
    progress = 100 if candidate == "ready" else 0
    safe_error = "" if candidate == "ready" else (error or "")[:500]
    try:
        index = max(0, int(item_index))
        count = max(0, int(item_count))
    except (TypeError, ValueError) as exc:
        raise ValueError("Playlist item position must be an integer.") from exc

    values = (
        (source_url or "")[:2048],
        (title or "")[:500],
        options_hash,
        format_selector or "",
        candidate,
        progress,
        asset,
        safe_error,
        (artist or "")[:500],
        (album or "")[:500],
        index,
        count,
        finished,
    )

    if identifier is not None:
        updated = await db.fetchrow(
            f"update {db.schema_sql}.download_jobs set "
            f"kind = 'playlist_item', source_url = $3, title = $4, "
            f"options_hash = $5, format_selector = $6, status = $7, "
            f"progress = $8, asset_id = $9, error = $10, artist = $11, "
            f"album = $12, item_index = $13, item_count = $14, "
            f"started_at = coalesce(started_at, $15), completed_at = $15, "
            f"cancel_requested = false, updated_at = now() "
            f"where id = $1 and user_id = $2 and playlist_id = $16 "
            f"and kind = 'playlist_item' returning {JOB_COLUMNS}",
            identifier,
            owner,
            *values,
            playlist,
        )
        if updated is not None:
            return dict(updated)

    record = await db.fetchrow(
        f"insert into {db.schema_sql}.download_jobs "
        f"(user_id, kind, playlist_id, source_url, title, options_hash, "
        f"format_selector, status, progress, asset_id, error, artist, album, "
        f"item_index, item_count, started_at, completed_at) "
        f"values ($1, 'playlist_item', $2, $3, $4, $5, $6, $7, $8, $9, "
        f"$10, $11, $12, $13, $14, $15, $15) returning {JOB_COLUMNS}",
        owner,
        playlist,
        *values,
    )
    if record is None:  # pragma: no cover - INSERT ... RETURNING always returns
        raise RuntimeError("Playlist item job insert returned no row.")
    return dict(record)


async def get_job(
    db: Database,
    job_id: str | UUID,
    user_id: str | UUID | None = None,
) -> dict[str, Any] | None:
    """Return one job, optionally scoped to its owner."""
    identifier = _as_uuid(job_id)
    if user_id is None:
        record = await db.fetchrow(
            f"select {JOB_COLUMNS} from {db.schema_sql}.download_jobs where id = $1",
            identifier,
        )
    else:
        record = await db.fetchrow(
            f"select {JOB_COLUMNS} from {db.schema_sql}.download_jobs "
            f"where id = $1 and user_id = $2",
            identifier,
            _as_uuid(user_id),
        )
    return _row(record)


async def list_jobs(
    db: Database,
    user_id: str | UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's jobs plus the matching total."""
    if status is not None and status not in JOB_STATUSES:
        raise ValueError("Invalid job status.")
    limit, offset = _clamp(limit, offset)
    owner = _as_uuid(user_id)

    conditions = ["user_id = $1"]
    args: list[Any] = [owner]
    if status is not None:
        args.append(status)
        conditions.append(f"status = ${len(args)}")
    where = " where " + " and ".join(conditions)

    total_row = await db.fetchrow(
        f"select count(*) as total from {db.schema_sql}.download_jobs{where}",
        *args,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    page_args = list(args)
    page_args.extend([limit, offset])
    rows = await db.fetch(
        f"select {JOB_COLUMNS} from {db.schema_sql}.download_jobs{where} "
        f"order by created_at desc, id desc "
        f"limit ${len(args) + 1} offset ${len(args) + 2}",
        *page_args,
    )
    return [dict(row) for row in rows], total


async def claim_next_job(db: Database) -> dict[str, Any] | None:
    """Atomically claim the oldest queued job and move it to ``resolving``."""
    schema_sql = db.schema_sql
    async with db.transaction() as connection:
        record = await connection.fetchrow(
            f"select {JOB_COLUMNS} from {schema_sql}.download_jobs "
            f"where status = 'queued' "
            f"order by created_at asc, id asc "
            f"for update skip locked limit 1"
        )
        if record is None:
            return None
        updated = await connection.fetchrow(
            f"update {schema_sql}.download_jobs "
            f"set status = 'resolving', started_at = now(), updated_at = now(), "
            f"error = '' where id = $1 returning {JOB_COLUMNS}",
            record["id"],
        )
        return _row(updated) or dict(record)


async def update_job(
    db: Database, job_id: str | UUID, **fields: Any
) -> dict[str, Any] | None:
    """Update whitelisted columns and return the new row."""
    assignments = ["updated_at = now()"]
    args: list[Any] = [_as_uuid(job_id)]
    for key, value in fields.items():
        if key not in UPDATABLE_COLUMNS:
            raise ValueError(f"Unsupported job field: {key}")
        args.append(value)
        assignments.append(f"{key} = ${len(args)}")

    record = await db.fetchrow(
        f"update {db.schema_sql}.download_jobs set {', '.join(assignments)} "
        f"where id = $1 returning {JOB_COLUMNS}",
        *args,
    )
    return _row(record)


async def mark_ready(
    db: Database,
    job_id: str | UUID,
    *,
    asset_id: str | UUID | None = None,
) -> dict[str, Any] | None:
    """Finish a job successfully."""
    fields: dict[str, Any] = {
        "status": "ready",
        "progress": 100,
        "current_item_progress": 100,
        "error": "",
        "completed_at": _now(),
    }
    if asset_id is not None:
        fields["asset_id"] = _as_uuid(asset_id)
    return await update_job(db, job_id, **fields)


async def mark_failed(
    db: Database, job_id: str | UUID, message: str
) -> dict[str, Any] | None:
    """Finish a job as failed with a safe, bounded message."""
    return await update_job(
        db,
        job_id,
        status="failed",
        error=(message or "Download failed.")[:500],
        completed_at=_now(),
    )


async def mark_cancelled(
    db: Database, job_id: str | UUID
) -> dict[str, Any] | None:
    """Finish a job as cancelled."""
    return await update_job(
        db,
        job_id,
        status="cancelled",
        cancel_requested=True,
        completed_at=_now(),
    )


async def request_cancel(
    db: Database, job_id: str | UUID
) -> dict[str, Any] | None:
    """Flag a job for cancellation; queued jobs are cancelled immediately."""
    record = await db.fetchrow(
        f"update {db.schema_sql}.download_jobs "
        f"set cancel_requested = true, "
        f"status = case when status = 'queued' then 'cancelled' else status end, "
        f"completed_at = case when status = 'queued' then now() else completed_at end, "
        f"updated_at = now() "
        f"where id = $1 returning {JOB_COLUMNS}",
        _as_uuid(job_id),
    )
    return _row(record)


async def recover_stale_jobs(db: Database, lease_seconds: int) -> int:
    """Re-queue jobs whose worker vanished beyond the lease.

    A job that was ``resolving``/``downloading``/``processing`` and has not been
    touched for longer than the lease is moved back to ``queued`` (and its
    attempt count is incremented) so a fresh worker can pick it up.
    """
    record = await db.fetchrow(
        "with stale as ("
        f"  update {db.schema_sql}.download_jobs "
        "  set status = 'queued', attempts = attempts + 1, started_at = null, "
        "      error = '', updated_at = now() "
        "  where status in ('resolving', 'downloading', 'processing') "
        "    and updated_at < now() - ($1::int * interval '1 second') "
        "  returning 1"
        ") select count(*) as total from stale",
        max(1, int(lease_seconds)),
    )
    return int(record["total"]) if record is not None else 0
