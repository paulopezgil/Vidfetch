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

import asyncio
import base64
import binascii
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Literal, Mapping
from uuid import UUID, uuid4

from ..core.db import Database
from .storage import Storage, StorageError

MAX_PAGE_SIZE = 200

TRACK_METADATA_COLUMNS = (
    "custom_title",
    "custom_artist",
    "custom_album",
)

MAX_FACET_LIMIT = 50
FACET_COLUMNS = {
    "artist": "custom_artist",
    "album": "custom_album",
}

MAX_COVER_BYTES = 5 * 1024 * 1024

# Extension and magic-byte prefix for each accepted cover type.
COVER_TYPES: dict[str, tuple[str, tuple[bytes, ...]]] = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
}
COVER_EXTENSIONS = ("jpg", "png", "webp")
COVER_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class CoverValidationError(ValueError):
    """Raised when an uploaded cover image is malformed or unsupported."""


def _is_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _magic_matches(content_type: str, data: bytes) -> bool:
    if content_type == "image/webp":
        return _is_webp(data)
    prefixes = COVER_TYPES.get(content_type, ("", ()))[1]
    return any(data.startswith(prefix) for prefix in prefixes)


def decode_cover(content_type: str, data: str) -> tuple[str, bytes]:
    """Validate a base64 cover upload and return ``(extension, bytes)``.

    The decoded payload must be at most five MiB and its magic bytes must match
    the declared content type. All errors are :class:`CoverValidationError`
    with a safe, user-facing message.
    """
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise CoverValidationError("Unsupported cover image type.")
    if not isinstance(data, str) or not data.strip():
        raise CoverValidationError("Cover image data is required.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CoverValidationError(
            "Cover image data must be valid base64."
        ) from exc
    if not raw:
        raise CoverValidationError("Cover image data is empty.")
    if len(raw) > MAX_COVER_BYTES:
        raise CoverValidationError(
            "Cover images must be 5 MiB or smaller."
        )
    if not _magic_matches(content_type, raw):
        raise CoverValidationError(
            "Cover image data does not match the declared content type."
        )
    if content_type == "image/webp":
        extension = "webp"
    else:
        extension = COVER_TYPES[content_type][0]
    return extension, raw


TRACKS_TITLE = (
    "coalesce(nullif(ut.custom_title, ''), nullif(j.title, ''), a.title, '')"
)

TRACKS_COLUMNS = (
    f"ut.id, ut.asset_id, j.id as job_id, a.canonical_id, {TRACKS_TITLE} as title, "
    "ut.custom_artist as artist, ut.custom_album as album, "
    "ut.cover_path, a.thumbnail_path, a.duration_seconds, a.file_size_bytes, "
    "a.output_ext, j.format_selector, j.playlist_id, 'ready' as status, "
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


TRACKS_WHERE = (
    "where ut.user_id = $1 and ut.deleted_at is null and a.status = 'ready' "
    "and ($2 = '' "
    f"or {TRACKS_TITLE} ilike '%' || $2 || '%' "
    "or coalesce(ut.custom_artist, '') ilike '%' || $2 || '%' "
    "or coalesce(ut.custom_album, '') ilike '%' || $2 || '%')"
)

TRACKS_WHERE_BY_ID = (
    "where ut.id = $1 and ut.user_id = $2 and ut.deleted_at is null "
    "and a.status = 'ready'"
)

TRACKS_WHERE_BY_IDS = (
    "where ut.user_id = $1 and ut.deleted_at is null and a.status = 'ready' "
    "and ut.id = any($2::uuid[])"
)

# The client derives a media kind from ``output_ext`` (leading dot stripped,
# lowercased). Mirror that rule in SQL so a page never mixes media kinds that
# the Songs/Videos views filter out client-side. Only the extension sets below
# are spliced into the statement; a caller-supplied kind is just a dictionary
# key and is never interpolated.
TRACK_EXTENSION = (
    "regexp_replace(lower(coalesce(a.output_ext, '')), '^\\.', '')"
)
AUDIO_EXTENSIONS = ("mp3", "m4a", "aac", "wav", "flac", "ogg", "opus")
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif", "avif", "bmp")


def _sql_extension_array(extensions: Iterable[str]) -> str:
    return "array[" + ", ".join(f"'{value}'" for value in extensions) + "]"


_AUDIO_EXTENSIONS_SQL = _sql_extension_array(AUDIO_EXTENSIONS)
_IMAGE_EXTENSIONS_SQL = _sql_extension_array(IMAGE_EXTENSIONS)
_AUDIO_PREDICATE = f"{TRACK_EXTENSION} = any({_AUDIO_EXTENSIONS_SQL})"
_IMAGE_PREDICATE = f"{TRACK_EXTENSION} = any({_IMAGE_EXTENSIONS_SQL})"

# Video is the complement: anything that is neither audio nor image, which
# includes NULL and unrecognised extensions, matching the frontend fallback.
TRACK_KIND_PREDICATES: dict[str, str] = {
    "audio": _AUDIO_PREDICATE,
    "image": _IMAGE_PREDICATE,
    "video": f"not ({_AUDIO_PREDICATE} or {_IMAGE_PREDICATE})",
}

TrackKind = Literal["audio", "video", "image"]


def _track_kind_filter(kind: str | None) -> str:
    """Return a SQL ``and`` clause for ``kind``, or ``""`` for no filter."""
    if kind is None:
        return ""
    predicate = TRACK_KIND_PREDICATES.get(kind)
    if predicate is None:
        raise ValueError("Invalid track kind.")
    return f" and ({predicate})"


# Whitelisted orderings. The title sort reuses the resolved-title expression
# from ``TRACKS_COLUMNS`` so it orders by exactly what the client displays, and
# falls back to the id for a deterministic tie-break (and therefore stable
# pagination). A caller-supplied value is only ever a dictionary key.
TRACK_SORTS: dict[str, str] = {
    "downloaded": "ut.downloaded_at desc, ut.id desc",
    "title": f"lower({TRACKS_TITLE}) asc, ut.id asc",
}

# The same ownership and visibility rules as TRACKS_WHERE, written as an
# UPDATE guard so a caller can never edit a track that is hidden, deleted, or
# no longer backed by a ready job/asset.
def _track_update_visible(schema_sql: str) -> str:
    return (
        "where ut.id = $1 and ut.user_id = $2 and ut.deleted_at is null "
        f"and exists (select 1 from {schema_sql}.media_assets a "
        "where a.id = ut.asset_id and a.status = 'ready') "
        f"and exists (select 1 from {schema_sql}.download_jobs j "
        "where j.user_id = ut.user_id and j.asset_id = ut.asset_id "
        "and j.status = 'ready' and j.library_hidden = false)"
    )


def _normalize_search(q: str | None) -> str:
    """Trim the search term; blank input means no filter."""
    return "" if q is None else str(q).strip()


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
    q: str | None = None,
    sort: str = "downloaded",
    kind: TrackKind | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's visible tracks.

    ``q`` filters case-insensitively on the resolved title, artist, or album.
    Whitespace-only input is treated as no filter. ``sort`` is one of
    :data:`TRACK_SORTS`: newest download first (the default) or resolved title
    ascending. Both orderings tie-break on the track id, so paging is stable.
    ``kind`` restricts the page to audio, video, or image tracks using the same
    output-extension rules as the client; ``None`` keeps every kind.
    """
    order_by = TRACK_SORTS.get(str(sort))
    if order_by is None:
        raise ValueError("Invalid track sort.")
    kind_filter = _track_kind_filter(kind)
    owner = _as_uuid(user_id)
    limit, offset = _clamp(limit, offset)
    search = _normalize_search(q)

    tracks_from = _tracks_from(db.schema_sql)
    tracks_where = f"{TRACKS_WHERE}{kind_filter}"

    total_row = await db.fetchrow(
        f"select count(*) as total {tracks_from} {tracks_where}",
        owner,
        search,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {TRACKS_COLUMNS} {tracks_from} {tracks_where} "
        f"order by {order_by} limit $3 offset $4",
        owner,
        search,
        limit,
        offset,
    )
    return [dict(row) for row in rows], total


async def get_track(
    db: Database,
    track_id: str | UUID,
    user_id: str | UUID,
) -> dict[str, Any] | None:
    """Return one visible track owned by ``user_id``, or ``None``."""
    identifier = _as_uuid(track_id)
    owner = _as_uuid(user_id)
    record = await db.fetchrow(
        f"select {TRACKS_COLUMNS} {_tracks_from(db.schema_sql)} "
        f"{TRACKS_WHERE_BY_ID}",
        identifier,
        owner,
    )
    return None if record is None else dict(record)


async def list_tracks_by_ids(
    db: Database,
    user_id: str | UUID,
    track_ids: Iterable[str | UUID],
) -> list[dict[str, Any]]:
    """Return the caller's visible tracks in the requested id order.

    Tracks that are deleted, hidden, no longer backed by a ready job/asset, or
    owned by somebody else are omitted. Duplicate ids are collapsed, so the
    result is a subsequence of the requested ordering. An empty input skips the
    query entirely.
    """
    owner = _as_uuid(user_id)
    ordered: list[UUID] = []
    seen: set[UUID] = set()
    for value in track_ids:
        identifier = _as_uuid(value)
        if identifier in seen:
            continue
        seen.add(identifier)
        ordered.append(identifier)
    if not ordered:
        return []

    rows = await db.fetch(
        f"select {TRACKS_COLUMNS} {_tracks_from(db.schema_sql)} "
        f"{TRACKS_WHERE_BY_IDS}",
        owner,
        ordered,
    )
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[identifier] for identifier in ordered if identifier in by_id]


async def update_track(
    db: Database,
    track_id: str | UUID,
    user_id: str | UUID,
    fields: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Update the caller's own editable track metadata.

    Only the columns named in ``fields`` are written. ``None`` is returned when
    the track is missing, owned by somebody else, deleted, hidden, or no longer
    backed by a ready job and asset, which the router maps to a 404.
    """
    identifier = _as_uuid(track_id)
    owner = _as_uuid(user_id)

    assignments = ["updated_at = now()"]
    args: list[Any] = [identifier, owner]
    for column in TRACK_METADATA_COLUMNS:
        if column not in fields:
            continue
        value = fields[column]
        if not isinstance(value, str):
            raise ValueError(f"{column} must be a string.")
        args.append(value)
        assignments.append(f"{column} = ${len(args)}")
    if len(args) == 2:
        raise ValueError("At least one metadata field is required.")

    update_sql = (
        f"update {db.schema_sql}.user_tracks ut "
        f"set {', '.join(assignments)} "
        f"{_track_update_visible(db.schema_sql)} "
        f"returning ut.id"
    )

    async with db.transaction() as connection:
        updated = await connection.fetchrow(update_sql, *args)
        if updated is None:
            return None
        record = await connection.fetchrow(
            f"select {TRACKS_COLUMNS} {_tracks_from(db.schema_sql)} "
            f"{TRACKS_WHERE_BY_ID}",
            identifier,
            owner,
        )
    return None if record is None else dict(record)


async def list_facets(
    db: Database,
    user_id: str | UUID,
    *,
    kind: str,
    q: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Group the caller's non-deleted tracks by artist or album.

    ``kind`` is limited to the whitelisted ``artist``/``album`` columns. Blank
    values are ignored, ``q`` filters case-insensitively, and the result is
    ordered by track count (descending) then name. The limit is clamped to
    1..50.
    """
    column = FACET_COLUMNS.get(kind)
    if column is None:
        raise ValueError("Unknown facet kind.")
    owner = _as_uuid(user_id)
    search = _normalize_search(q)
    try:
        page_size = max(1, min(MAX_FACET_LIMIT, int(limit)))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer.") from exc

    rows = await db.fetch(
        f"select btrim(ut.{column}) as name, count(*)::int as track_count "
        f"from {db.schema_sql}.user_tracks ut "
        f"where ut.user_id = $1 and ut.deleted_at is null "
        f"and btrim(coalesce(ut.{column}, '')) <> '' "
        f"and ($2 = '' or btrim(ut.{column}) ilike '%' || $2 || '%') "
        f"group by btrim(ut.{column}) "
        f"order by count(*) desc, name asc "
        f"limit $3",
        owner,
        search,
        page_size,
    )
    return [dict(row) for row in rows]


# -- cover art --------------------------------------------------------------


def cover_relative_path(
    user_id: str | UUID,
    track_id: str | UUID,
    extension: str,
) -> str:
    """Return the storage-relative path for a track's cover image."""
    ext = extension.split(".")[-1].lower()
    if ext not in COVER_EXTENSIONS:
        raise ValueError("Unsupported cover extension.")
    return f"covers/{_as_uuid(user_id)}/{_as_uuid(track_id)}.{ext}"


def cover_media_type(relative: str | Path) -> str:
    """Return the response media type for a stored cover path."""
    suffix = Path(str(relative)).suffix.lstrip(".").lower()
    return COVER_MEDIA_TYPES.get(suffix, "application/octet-stream")


def _write_cover(storage: Storage, relative: str, payload: bytes) -> Path:
    destination = storage.validate_relative_path(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{uuid4().hex}.tmp"
    )
    try:
        temporary.write_bytes(payload)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return destination


async def _remove_cover_files(
    storage: Storage,
    user_id: UUID,
    track_id: UUID,
    *,
    keep: str | None = None,
    stale: str | None = None,
) -> None:
    """Best-effort removal of a track's stale cover files."""
    candidates = {
        cover_relative_path(user_id, track_id, extension)
        for extension in COVER_EXTENSIONS
    }
    if stale:
        candidates.add(stale)
    if keep is not None:
        candidates.discard(keep)
    for relative in candidates:
        try:
            await asyncio.to_thread(storage.delete_asset_file, relative)
        except (OSError, StorageError):
            # A stale symlink or directory is refused by Storage; never let
            # cleanup failure fail an otherwise valid upload/delete.
            continue


async def _select_cover_row(
    connection: Any,
    schema_sql: str,
    track_id: UUID,
    user_id: UUID,
) -> Any:
    return await connection.fetchrow(
        f"select ut.id, ut.cover_path from {schema_sql}.user_tracks ut "
        f"where ut.id = $1 and ut.user_id = $2 and ut.deleted_at is null "
        f"for update",
        track_id,
        user_id,
    )


async def set_cover(
    db: Database,
    storage: Storage,
    track_id: str | UUID,
    user_id: str | UUID,
    *,
    content_type: str,
    data: str,
) -> str | None:
    """Validate, store, and record a new cover image for the caller's track.

    Returns the stored relative path, or ``None`` when the track is not found
    or not owned by ``user_id``. The image is written atomically and any stale
    cover with another extension is removed.
    """
    identifier = _as_uuid(track_id)
    owner = _as_uuid(user_id)
    extension, payload = decode_cover(content_type, data)
    relative = cover_relative_path(owner, identifier, extension)

    async with db.transaction() as connection:
        row = await _select_cover_row(
            connection, db.schema_sql, identifier, owner
        )
        if row is None:
            return None
        await asyncio.to_thread(_write_cover, storage, relative, payload)
        try:
            await connection.execute(
                f"update {db.schema_sql}.user_tracks "
                f"set cover_path = $3, updated_at = now() "
                f"where id = $1 and user_id = $2",
                identifier,
                owner,
                relative,
            )
        except Exception:
            try:
                await asyncio.to_thread(
                    storage.delete_asset_file, relative
                )
            except (OSError, StorageError):
                pass
            raise
        previous = row["cover_path"]

    await _remove_cover_files(
        storage, owner, identifier, keep=relative, stale=previous
    )
    return relative


async def delete_cover(
    db: Database,
    storage: Storage,
    track_id: str | UUID,
    user_id: str | UUID,
) -> bool:
    """Clear the caller's track cover and delete the stored file.

    Returns ``False`` when the track is missing or not owned by ``user_id``.
    """
    identifier = _as_uuid(track_id)
    owner = _as_uuid(user_id)

    async with db.transaction() as connection:
        row = await _select_cover_row(
            connection, db.schema_sql, identifier, owner
        )
        if row is None:
            return False
        await connection.execute(
            f"update {db.schema_sql}.user_tracks "
            f"set cover_path = null, updated_at = now() "
            f"where id = $1 and user_id = $2",
            identifier,
            owner,
        )
        previous = row["cover_path"]

    await _remove_cover_files(
        storage, owner, identifier, stale=previous
    )
    return True


async def resolve_cover_path(
    db: Database,
    storage: Storage,
    track_id: str | UUID,
    user_id: str | UUID,
) -> Path | None:
    """Return the on-disk cover for a track, rejecting unsafe paths."""
    identifier = _as_uuid(track_id)
    owner = _as_uuid(user_id)
    record = await db.fetchrow(
        f"select ut.cover_path from {db.schema_sql}.user_tracks ut "
        f"where ut.id = $1 and ut.user_id = $2 and ut.deleted_at is null",
        identifier,
        owner,
    )
    if record is None:
        return None
    relative = (record["cover_path"] or "").strip()
    if not relative:
        return None
    try:
        path = storage.validate_relative_path(relative)
    except (OSError, StorageError):
        return None
    # ``validate_relative_path`` resolves symlinks, so check the lexical entry
    # as well: a symlink planted at the cover path must never be served even
    # when it points at another file inside the storage root.
    lexical = storage.root.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink() or lexical.is_symlink() or not path.is_file():
        return None
    return path
