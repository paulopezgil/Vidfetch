"""Global media-asset cache and claim/lease coordination.

One row per ``(canonical_id, options_hash)``. The claim algorithm serializes
concurrent jobs that want the same output:

* no row -> insert with a lease and claim it
* ``ready`` and the file validates -> cache hit
* ``ready`` but the file is missing/corrupt -> repair (re-claim)
* ``processing`` with a live lease -> wait
* ``failed`` or an expired lease -> re-claim with a new lease

All timestamps are timezone-aware UTC datetimes. The asyncpg driver returns
aware ``datetime`` values for ``timestamptz``; naive values (for example from a
test double) are treated as UTC rather than compared against aware values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from ..core.db import Database

ASSET_COLUMNS = (
    "id, canonical_id, extractor_key, source_url, title, duration_seconds, "
    "options_hash, options_schema_version, format_selector, output_ext, "
    "file_path, thumbnail_path, file_size_bytes, file_sha256, status, error, "
    "attempts, claimed_at, lease_until, created_at, updated_at, last_accessed_at"
)

# Last access is written at most this often per asset.
ACCESS_TOUCH_THROTTLE_SECONDS = 60


@dataclass
class AssetClaim:
    """The result of :func:`claim_asset`."""

    asset: dict[str, Any]
    claimed: bool = False
    cache_hit: bool = False
    wait: bool = False


def canonical_id(extractor_key: str, media_id: str) -> str:
    """Build ``<extractor>:<id>``, the stable cross-user identity."""
    key = (extractor_key or "").strip().lower()
    identifier = (media_id or "").strip()
    if not key:
        raise ValueError("extractor_key is required.")
    if not identifier:
        raise ValueError("media_id is required.")
    return f"{key}:{identifier}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return None


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid asset id.") from exc


def _row(record: Any) -> dict[str, Any] | None:
    return None if record is None else dict(record)


def _validate_relative(rel: str, label: str) -> str:
    candidate = (rel or "").strip()
    if not candidate:
        raise ValueError(f"{label} is required.")
    if candidate.startswith("/") or "\\" in candidate or "\x00" in candidate:
        raise ValueError(f"{label} must be a relative path.")
    if any(part == ".." for part in PurePosixPath(candidate).parts):
        raise ValueError(f"{label} must not contain parent traversal.")
    return candidate


def _asset_file_valid(storage: Any, asset: dict[str, Any]) -> bool:
    """Return True when the stored file exists with the recorded size."""
    relative = (asset.get("file_path") or "").strip()
    expected = asset.get("file_size_bytes")
    if not relative or expected is None:
        return False
    try:
        resolved = storage.validate_relative_path(relative)
        lexical = storage.root.joinpath(*PurePosixPath(relative).parts)
        if lexical.is_symlink() or not resolved.is_file():
            return False
        return resolved.stat().st_size == int(expected)
    except (OSError, ValueError):
        return False


async def _touch_locked(
    connection: Any,
    schema_sql: str,
    asset: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Update ``last_accessed_at`` inside a claim, at most once per minute."""
    last = _as_aware(asset.get("last_accessed_at"))
    if last is not None and (now - last).total_seconds() < ACCESS_TOUCH_THROTTLE_SECONDS:
        return asset
    record = await connection.fetchrow(
        f"update {schema_sql}.media_assets "
        f"set last_accessed_at = $2, updated_at = now() "
        f"where id = $1 returning {ASSET_COLUMNS}",
        asset["id"],
        now,
    )
    return _row(record) or asset


async def claim_asset(
    db: Database,
    storage: Any,
    *,
    canonical_id: str,
    extractor_key: str,
    source_url: str,
    title: str,
    duration_seconds: int | None,
    options_hash: str,
    format_selector: str,
    lease_seconds: int,
) -> AssetClaim:
    """Atomically claim, reuse, or wait for an asset."""
    if not canonical_id or not canonical_id.strip():
        raise ValueError("canonical_id is required.")
    if not options_hash or not options_hash.strip():
        raise ValueError("options_hash is required.")
    lease = max(1, int(lease_seconds))
    now = _now()
    lease_until = now + timedelta(seconds=lease)
    schema_sql = db.schema_sql

    async with db.transaction() as connection:
        record = await connection.fetchrow(
            f"select {ASSET_COLUMNS} from {schema_sql}.media_assets "
            f"where canonical_id = $1 and options_hash = $2 "
            f"for update",
            canonical_id,
            options_hash,
        )
        if record is None:
            inserted = await connection.fetchrow(
                f"insert into {schema_sql}.media_assets "
                f"(canonical_id, extractor_key, source_url, title, "
                f"duration_seconds, options_hash, format_selector, status, "
                f"attempts, claimed_at, lease_until, last_accessed_at) "
                f"values ($1, $2, $3, $4, $5, $6, $7, 'processing', 1, $8, $9, $8) "
                f"returning {ASSET_COLUMNS}",
                canonical_id,
                (extractor_key or "").strip().lower(),
                source_url or "",
                title or "",
                duration_seconds,
                options_hash,
                format_selector or "",
                now,
                lease_until,
            )
            return AssetClaim(asset=_row(inserted) or {}, claimed=True)

        asset = dict(record)
        status = asset.get("status")

        if status == "ready":
            if _asset_file_valid(storage, asset):
                touched = await _touch_locked(
                    connection, schema_sql, asset, now
                )
                return AssetClaim(asset=touched, cache_hit=True)
            # Missing or corrupt file: repair by re-claiming.

        if status == "processing":
            current_lease = _as_aware(asset.get("lease_until"))
            if current_lease is not None and current_lease > now:
                return AssetClaim(asset=asset, wait=True)

        claimed = await connection.fetchrow(
            f"update {schema_sql}.media_assets "
            f"set status = 'processing', error = '', attempts = attempts + 1, "
            f"claimed_at = $2, lease_until = $3, updated_at = now() "
            f"where id = $1 returning {ASSET_COLUMNS}",
            asset["id"],
            now,
            lease_until,
        )
        return AssetClaim(asset=_row(claimed) or asset, claimed=True)


async def mark_ready(
    db: Database,
    asset_id: str | UUID,
    *,
    file_path: str,
    file_size_bytes: int,
    output_ext: str,
    thumbnail_path: str | None,
    file_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Finalize a claimed asset."""
    relative = _validate_relative(file_path, "file_path")
    thumbnail = (
        _validate_relative(thumbnail_path, "thumbnail_path")
        if thumbnail_path
        else None
    )
    record = await db.fetchrow(
        f"update {db.schema_sql}.media_assets "
        f"set status = 'ready', error = '', file_path = $2, "
        f"file_size_bytes = $3, output_ext = $4, thumbnail_path = $5, "
        f"file_sha256 = $6, lease_until = null, claimed_at = null, "
        f"last_accessed_at = now(), updated_at = now() "
        f"where id = $1 returning {ASSET_COLUMNS}",
        _as_uuid(asset_id),
        relative,
        int(file_size_bytes),
        (output_ext or "").strip().lower(),
        thumbnail,
        file_sha256,
    )
    return _row(record)


async def mark_failed(
    db: Database, asset_id: str | UUID, message: str
) -> dict[str, Any] | None:
    """Mark an asset as failed with a safe message, releasing its lease."""
    record = await db.fetchrow(
        f"update {db.schema_sql}.media_assets "
        f"set status = 'failed', error = $2, lease_until = null, "
        f"claimed_at = null, updated_at = now() "
        f"where id = $1 returning {ASSET_COLUMNS}",
        _as_uuid(asset_id),
        (message or "Download failed.")[:500],
    )
    return _row(record)


async def renew_lease(
    db: Database, asset_id: str | UUID, lease_seconds: int
) -> dict[str, Any] | None:
    """Extend a processing asset's lease."""
    record = await db.fetchrow(
        f"update {db.schema_sql}.media_assets "
        f"set lease_until = $2, updated_at = now() "
        f"where id = $1 and status = 'processing' returning {ASSET_COLUMNS}",
        _as_uuid(asset_id),
        _now() + timedelta(seconds=max(1, int(lease_seconds))),
    )
    return _row(record)


async def get_asset(
    db: Database, asset_id: str | UUID
) -> dict[str, Any] | None:
    record = await db.fetchrow(
        f"select {ASSET_COLUMNS} from {db.schema_sql}.media_assets where id = $1",
        _as_uuid(asset_id),
    )
    return _row(record)


async def touch_accessed(
    db: Database,
    asset_id: str | UUID,
    *,
    throttle_seconds: int = ACCESS_TOUCH_THROTTLE_SECONDS,
) -> bool:
    """Touch ``last_accessed_at`` at most once per ``throttle_seconds``.

    Returns True when a row was updated.
    """
    cutoff = _now() - timedelta(seconds=max(0, int(throttle_seconds)))
    status = await db.execute(
        f"update {db.schema_sql}.media_assets set last_accessed_at = now() "
        "where id = $1 and (last_accessed_at is null or last_accessed_at <= $2)",
        _as_uuid(asset_id),
        cutoff,
    )
    try:
        return str(status).rsplit(" ", 1)[-1] == "1"
    except (AttributeError, IndexError):  # pragma: no cover - defensive
        return False
