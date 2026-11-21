"""Per-user playlist metadata and ordered item tracking.

Playlists are scoped by ``user_id``; playlist items are scoped through their
parent playlist. Every query that can be reached from a request is either
explicitly owner-scoped or must be preceded by an ownership check in the
router.

Item positions are 1-based so the UI can display "video N of M" without an
offset. :func:`replace_items` keeps rows (and therefore their media asset
links) when a video is still present, moves surviving rows to their new
position, and deletes rows that disappeared from the source playlist. Shared
media assets are never deleted here.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping
from uuid import UUID

from ..core.db import Database

MAX_PAGE_SIZE = 200

PLAYLIST_COLUMNS = (
    "id, user_id, canonical_id, source_url, title, channel, thumbnail_path, "
    "item_count, options_hash, format_selector, status, created_at, updated_at"
)

PLAYLIST_ITEM_COLUMNS = (
    "id, playlist_id, position, canonical_id, source_url, title, "
    "duration_seconds, asset_id, job_id, status, error, created_at, updated_at"
)

PLAYLIST_STATUSES = frozenset(
    {"pending", "downloading", "ready", "partial", "failed", "cancelled"}
)

PLAYLIST_ITEM_STATUSES = frozenset(
    {"pending", "downloading", "ready", "failed", "cancelled"}
)

# Columns a caller may update through :func:`update_playlist`.
PLAYLIST_UPDATABLE_COLUMNS = frozenset(
    {
        "canonical_id",
        "source_url",
        "title",
        "channel",
        "thumbnail_path",
        "item_count",
        "options_hash",
        "format_selector",
        "status",
    }
)


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid playlist id.") from exc


def _row(record: Any) -> dict[str, Any] | None:
    return None if record is None else dict(record)


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


def playlist_cover_path(playlist_id: str | UUID) -> str:
    """Return the storage-relative cover path used for a playlist."""
    return f"playlists/{_as_uuid(playlist_id)}.jpg"


def _duration(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_status(status: str, allowed: frozenset[str], label: str) -> str:
    candidate = str(status or "").strip()
    if candidate not in allowed:
        raise ValueError(f"Invalid {label} status.")
    return candidate


async def upsert_playlist(
    db: Database,
    *,
    user_id: str | UUID,
    canonical_id: str,
    source_url: str,
    title: str,
    channel: str,
    item_count: int,
    options_hash: str,
    format_selector: str,
    thumbnail_path: str | None = None,
) -> dict[str, Any]:
    """Insert or refresh the caller's playlist for one output-intent hash."""
    if not isinstance(canonical_id, str) or not canonical_id.strip():
        raise ValueError("canonical_id is required.")
    if not isinstance(options_hash, str) or not options_hash.strip():
        raise ValueError("options_hash is required.")
    try:
        count = max(0, int(item_count))
    except (TypeError, ValueError) as exc:
        raise ValueError("item_count must be an integer.") from exc

    record = await db.fetchrow(
        f"insert into public.playlists "
        f"(user_id, canonical_id, source_url, title, channel, thumbnail_path, "
        f"item_count, options_hash, format_selector) "
        f"values ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        f"on conflict (user_id, canonical_id, options_hash) do update set "
        f"source_url = excluded.source_url, "
        f"title = excluded.title, "
        f"channel = excluded.channel, "
        f"thumbnail_path = coalesce(excluded.thumbnail_path, "
        f"public.playlists.thumbnail_path), "
        f"item_count = excluded.item_count, "
        f"format_selector = excluded.format_selector, "
        f"updated_at = now() "
        f"returning {PLAYLIST_COLUMNS}",
        _as_uuid(user_id),
        canonical_id.strip(),
        (source_url or "")[:2048],
        (title or "")[:500],
        (channel or "")[:500],
        thumbnail_path,
        count,
        options_hash,
        format_selector or "",
    )
    if record is None:  # pragma: no cover - INSERT ... RETURNING always returns
        raise RuntimeError("Playlist upsert returned no row.")
    return dict(record)


async def get_playlist(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID | None = None,
) -> dict[str, Any] | None:
    """Return one playlist, optionally scoped to its owner."""
    identifier = _as_uuid(playlist_id)
    if user_id is None:
        record = await db.fetchrow(
            f"select {PLAYLIST_COLUMNS} from public.playlists where id = $1",
            identifier,
        )
    else:
        record = await db.fetchrow(
            f"select {PLAYLIST_COLUMNS} from public.playlists "
            f"where id = $1 and user_id = $2",
            identifier,
            _as_uuid(user_id),
        )
    return _row(record)


async def list_playlists(
    db: Database,
    user_id: str | UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's playlists plus the total count."""
    limit, offset = _clamp(limit, offset)
    owner = _as_uuid(user_id)

    total_row = await db.fetchrow(
        "select count(*) as total from public.playlists where user_id = $1",
        owner,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {PLAYLIST_COLUMNS} from public.playlists "
        f"where user_id = $1 "
        f"order by created_at desc, id desc "
        f"limit $2 offset $3",
        owner,
        limit,
        offset,
    )
    return [dict(row) for row in rows], total


async def list_items(
    db: Database, playlist_id: str | UUID
) -> list[dict[str, Any]]:
    """Return a playlist's items in source order."""
    rows = await db.fetch(
        f"select {PLAYLIST_ITEM_COLUMNS} from public.playlist_items "
        f"where playlist_id = $1 order by position asc, id asc",
        _as_uuid(playlist_id),
    )
    return [dict(row) for row in rows]


def _dedupe_entries(
    entries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Drop duplicate non-empty canonical ids, preserving source order."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("Playlist entries must be mappings.")
        canonical = str(entry.get("canonical_id") or "").strip()
        if canonical:
            if canonical in seen:
                continue
            seen.add(canonical)
        duration = entry.get("duration_seconds")
        if duration is None:
            duration = entry.get("duration")
        result.append(
            {
                "canonical_id": canonical,
                "source_url": str(
                    entry.get("source_url")
                    or entry.get("url")
                    or entry.get("webpage_url")
                    or ""
                )[:2048],
                "title": str(entry.get("title") or "")[:500],
                "duration_seconds": _duration(duration),
            }
        )
    return result


async def replace_items(
    db: Database,
    playlist_id: str | UUID,
    entries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Reconcile playlist items with a freshly resolved flat entry list.

    Matching prefers ``(playlist_id, canonical_id)`` so a video keeps its
    asset link when it moves position, then falls back to
    ``(playlist_id, position)``. Existing rows are temporarily parked at
    negative positions inside the transaction to avoid unique-position
    collisions while rows move around. Rows no longer present are deleted;
    their media assets are left untouched.
    """
    identifier = _as_uuid(playlist_id)
    normalized = _dedupe_entries(entries)

    async with db.transaction() as connection:
        existing = await connection.fetch(
            f"select {PLAYLIST_ITEM_COLUMNS} from public.playlist_items "
            f"where playlist_id = $1 order by position asc for update",
            identifier,
        )
        existing_rows = [dict(row) for row in existing]

        if existing_rows:
            # Move every row out of the positive position space first. The
            # unique constraint is checked per statement, so this lets rows
            # swap positions without a transient duplicate.
            await connection.execute(
                "update public.playlist_items set position = -position "
                "where playlist_id = $1",
                identifier,
            )

        by_position = {int(row["position"]): row for row in existing_rows}
        by_canonical = {
            str(row["canonical_id"]): row
            for row in existing_rows
            if str(row.get("canonical_id") or "")
        }
        matched: set[Any] = set()
        result: list[dict[str, Any]] = []

        for position, entry in enumerate(normalized, start=1):
            canonical = entry["canonical_id"]
            match = by_canonical.get(canonical) if canonical else None
            if match is None:
                match = by_position.get(position)

            if match is not None and match["id"] not in matched:
                matched.add(match["id"])
                updated = await connection.fetchrow(
                    f"update public.playlist_items set "
                    f"position = $3, canonical_id = $4, source_url = $5, "
                    f"title = $6, duration_seconds = $7, "
                    f"asset_id = case when canonical_id = $4 then asset_id "
                    f"else null end, "
                    f"job_id = case when canonical_id = $4 then job_id "
                    f"else null end, "
                    f"status = case when canonical_id = $4 then status "
                    f"else 'pending' end, "
                    f"error = case when canonical_id = $4 then error else '' end, "
                    f"updated_at = now() "
                    f"where id = $1 and playlist_id = $2 "
                    f"returning {PLAYLIST_ITEM_COLUMNS}",
                    match["id"],
                    identifier,
                    position,
                    canonical,
                    entry["source_url"],
                    entry["title"],
                    entry["duration_seconds"],
                )
                if updated is not None:
                    result.append(dict(updated))
                continue

            inserted = await connection.fetchrow(
                f"insert into public.playlist_items "
                f"(playlist_id, position, canonical_id, source_url, title, "
                f"duration_seconds) "
                f"values ($1, $2, $3, $4, $5, $6) "
                f"returning {PLAYLIST_ITEM_COLUMNS}",
                identifier,
                position,
                canonical,
                entry["source_url"],
                entry["title"],
                entry["duration_seconds"],
            )
            if inserted is not None:
                result.append(dict(inserted))

        if existing_rows:
            # Anything still parked at a negative position is stale.
            await connection.execute(
                "delete from public.playlist_items "
                "where playlist_id = $1 and position < 0",
                identifier,
            )

    return result


async def update_item(
    db: Database,
    playlist_id: str | UUID,
    position: int,
    *,
    status: str,
    asset_id: str | UUID | None = None,
    job_id: str | UUID | None = None,
    error: str = "",
    canonical_id: str | None = None,
    source_url: str | None = None,
    title: str | None = None,
    duration_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Update one item by its source position.

    ``asset_id`` and ``job_id`` are only changed when supplied; optional
    metadata arguments let the worker cache a lazily resolved item.
    """
    safe_status = _validate_status(status, PLAYLIST_ITEM_STATUSES, "playlist item")
    assignments = ["status = $3", "error = $4", "updated_at = now()"]
    args: list[Any] = [
        _as_uuid(playlist_id),
        max(1, int(position)),
        safe_status,
        (error or "")[:500],
    ]

    def add(column: str, value: Any) -> None:
        args.append(value)
        assignments.append(f"{column} = ${len(args)}")

    if asset_id is not None:
        add("asset_id", _as_uuid(asset_id))
    if job_id is not None:
        add("job_id", _as_uuid(job_id))
    if canonical_id is not None:
        add("canonical_id", str(canonical_id).strip())
    if source_url is not None:
        add("source_url", str(source_url)[:2048])
    if title is not None:
        add("title", str(title)[:500])
    if duration_seconds is not None:
        add("duration_seconds", _duration(duration_seconds))

    record = await db.fetchrow(
        f"update public.playlist_items set {', '.join(assignments)} "
        f"where playlist_id = $1 and position = $2 "
        f"returning {PLAYLIST_ITEM_COLUMNS}",
        *args,
    )
    return _row(record)


async def update_playlist(
    db: Database, playlist_id: str | UUID, **fields: Any
) -> dict[str, Any] | None:
    """Update whitelisted playlist columns and return the new row."""
    assignments = ["updated_at = now()"]
    args: list[Any] = [_as_uuid(playlist_id)]
    for key, value in fields.items():
        if key not in PLAYLIST_UPDATABLE_COLUMNS:
            raise ValueError(f"Unsupported playlist field: {key}")
        if key == "status":
            value = _validate_status(value, PLAYLIST_STATUSES, "playlist")
        args.append(value)
        assignments.append(f"{key} = ${len(args)}")

    record = await db.fetchrow(
        f"update public.playlists set {', '.join(assignments)} "
        f"where id = $1 returning {PLAYLIST_COLUMNS}",
        *args,
    )
    return _row(record)


async def delete_playlist(
    db: Database, playlist_id: str | UUID, user_id: str | UUID
) -> bool:
    """Delete a playlist and (by cascade) its items. Media assets remain."""
    record = await db.fetchrow(
        "delete from public.playlists where id = $1 and user_id = $2 "
        "returning id",
        _as_uuid(playlist_id),
        _as_uuid(user_id),
    )
    return record is not None
