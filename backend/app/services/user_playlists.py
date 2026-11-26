"""Per-user curated playlists over per-user tracks.

A curated playlist is owned by exactly one user and holds that user's own
``user_tracks`` rows in an explicit order. Unlike ``playlists`` (a downloaded
source playlist), it is never refreshed from a remote source and never crosses
user boundaries.

Every query here is owner-scoped: the playlist row carries ``user_id`` and the
membership queries are only reached after the caller's playlist ownership has
been checked. ``track_count`` and the detail items deliberately reuse the same
visibility predicate as ``GET /api/tracks``, so a track that the user hid or
that lost its ready asset disappears from the playlist view without its
membership row being deleted.

Positions are 0-based and compacted to ``0..n-1``. The database's unique
``(playlist_id, position)`` constraint is deferred, so a reorder can rewrite
every position inside one transaction without transient collisions.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping
from uuid import UUID

from ..core.db import Database
from . import tracks

MAX_PAGE_SIZE = 200
MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 500


class UserPlaylistNotFoundError(ValueError):
    """The playlist is missing, not owned by the caller, or soft-deleted."""


class UserPlaylistTrackNotFoundError(ValueError):
    """The track is not one of the caller's visible tracks (or not a member)."""


class InvalidTrackOrderError(ValueError):
    """The requested order is not an exact permutation of the membership."""


class ShareRecipientError(ValueError):
    """The email does not resolve to another approved account.

    The message is deliberately generic so the caller cannot use the share
    endpoint to discover which addresses are registered or pending approval.
    """


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid playlist id.") from exc


def _clamp(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(MAX_PAGE_SIZE, int(limit))), max(0, int(offset))


def _clean_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValueError("Playlist name must be a string.")
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Playlist name is required.")
    if len(trimmed) > MAX_NAME_LENGTH:
        raise ValueError(
            f"Playlist name must be at most {MAX_NAME_LENGTH} characters."
        )
    return trimmed


def _clean_description(description: Any) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise ValueError("Playlist description must be a string.")
    trimmed = description.strip()
    if len(trimmed) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            "Playlist description must be at most "
            f"{MAX_DESCRIPTION_LENGTH} characters."
        )
    return trimmed


def _visible_track_predicate(schema_sql: str) -> str:
    """The ``GET /api/tracks`` visibility rule for a joined ``ut``/``a`` row.

    The caller must join ``user_tracks ut`` and ``media_assets a`` and supply
    the ownership condition; this fragment adds the deleted/ready/hidden part.
    """
    return (
        "ut.deleted_at is null and a.status = 'ready' "
        f"and exists (select 1 from {schema_sql}.download_jobs j "
        "where j.user_id = ut.user_id and j.asset_id = ut.asset_id "
        "and j.status = 'ready' and j.library_hidden = false)"
    )


def _track_count_sql(schema_sql: str, alias: str = "p") -> str:
    """Count only the playlist's currently visible tracks."""
    return (
        f"(select count(*) from {schema_sql}.user_playlist_tracks t "
        f"where t.playlist_id = {alias}.id "
        f"and exists (select 1 from {schema_sql}.user_tracks ut "
        f"join {schema_sql}.media_assets a on a.id = ut.asset_id "
        f"where ut.id = t.user_track_id and ut.user_id = {alias}.user_id "
        f"and {_visible_track_predicate(schema_sql)})) as track_count"
    )


def _playlist_columns(schema_sql: str, alias: str = "p") -> str:
    return (
        f"{alias}.id, {alias}.user_id, {alias}.name, {alias}.description, "
        f"{alias}.cover_path, {alias}.created_at, {alias}.updated_at, "
        f"{_track_count_sql(schema_sql, alias)}"
    )


async def list_user_playlists(
    db: Database,
    user_id: str | UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of the caller's live playlists, newest updated first."""
    owner = _as_uuid(user_id)
    limit, offset = _clamp(limit, offset)
    schema_sql = db.schema_sql

    total_row = await db.fetchrow(
        f"select count(*) as total from {schema_sql}.user_playlists p "
        f"where p.user_id = $1 and p.deleted_at is null",
        owner,
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {_playlist_columns(schema_sql)} "
        f"from {schema_sql}.user_playlists p "
        f"where p.user_id = $1 and p.deleted_at is null "
        f"order by p.updated_at desc, p.id desc limit $2 offset $3",
        owner,
        limit,
        offset,
    )
    return [dict(row) for row in rows], total


async def get_user_playlist(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
) -> dict[str, Any] | None:
    """Return one live playlist owned by ``user_id``, or ``None``."""
    identifier = _as_uuid(playlist_id)
    owner = _as_uuid(user_id)
    record = await db.fetchrow(
        f"select {_playlist_columns(db.schema_sql)} "
        f"from {db.schema_sql}.user_playlists p "
        f"where p.id = $1 and p.user_id = $2 and p.deleted_at is null",
        identifier,
        owner,
    )
    return None if record is None else dict(record)


async def create_user_playlist(
    db: Database,
    user_id: str | UUID,
    *,
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create an empty playlist and return its ``UserPlaylistOut`` row."""
    owner = _as_uuid(user_id)
    cleaned_name = _clean_name(name)
    cleaned_description = _clean_description(description)
    record = await db.fetchrow(
        f"insert into {db.schema_sql}.user_playlists "
        f"(user_id, name, description) values ($1, $2, $3) "
        f"returning id, user_id, name, description, cover_path, "
        f"created_at, updated_at, 0 as track_count",
        owner,
        cleaned_name,
        cleaned_description,
    )
    if record is None:  # pragma: no cover - INSERT ... RETURNING always returns
        raise RuntimeError("Playlist insert returned no row.")
    return dict(record)


async def update_user_playlist(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
    fields: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Update only the provided fields on the caller's live playlist.

    Returns ``None`` when the playlist is missing, owned by somebody else, or
    soft-deleted, which the router maps to a 404.
    """
    identifier = _as_uuid(playlist_id)
    owner = _as_uuid(user_id)

    assignments = ["updated_at = now()"]
    args: list[Any] = [identifier, owner]
    if "name" in fields:
        args.append(_clean_name(fields["name"]))
        assignments.append(f"name = ${len(args)}")
    if "description" in fields:
        args.append(_clean_description(fields["description"]))
        assignments.append(f"description = ${len(args)}")
    if len(args) == 2:
        raise ValueError("At least one playlist field is required.")

    record = await db.fetchrow(
        f"update {db.schema_sql}.user_playlists p "
        f"set {', '.join(assignments)} "
        f"where p.id = $1 and p.user_id = $2 and p.deleted_at is null "
        f"returning {_playlist_columns(db.schema_sql)}",
        *args,
    )
    return None if record is None else dict(record)


async def delete_user_playlist(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
) -> bool:
    """Soft-delete the caller's playlist; the rows are retained for audit."""
    record = await db.fetchrow(
        f"update {db.schema_sql}.user_playlists "
        f"set deleted_at = now() "
        f"where id = $1 and user_id = $2 and deleted_at is null "
        f"returning id",
        _as_uuid(playlist_id),
        _as_uuid(user_id),
    )
    return record is not None


async def list_track_ids(
    db: Database, playlist_id: str | UUID
) -> list[UUID]:
    """Return the playlist's membership ids in position order.

    This is not owner-scoped by itself: it must only be called after the
    playlist's ownership has been verified.
    """
    rows = await db.fetch(
        f"select t.user_track_id from "
        f"{db.schema_sql}.user_playlist_tracks t "
        f"where t.playlist_id = $1 "
        f"order by t.position asc, t.user_track_id asc",
        _as_uuid(playlist_id),
    )
    return [row["user_track_id"] for row in rows]


async def get_playlist_with_tracks(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Return an owned playlist and its visible tracks in playlist order."""
    playlist = await get_user_playlist(db, playlist_id, user_id)
    if playlist is None:
        return None
    identifiers = await list_track_ids(db, playlist["id"])
    items = await tracks.list_tracks_by_ids(db, user_id, identifiers)
    return playlist, items


async def list_shared_with_user(
    db: Database,
    user_id: str | UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of live playlists shared with ``user_id``.

    The rows carry the owner's email and ``is_owner=False`` so the caller can
    render a read-only "shared with me" collection. The track count keeps the
    same visibility rule and the owner's ``user_tracks`` ownership as the
    owner-facing list, so a shared playlist advertises exactly what the owner
    can see.
    """
    viewer = _as_uuid(user_id)
    limit, offset = _clamp(limit, offset)
    schema_sql = db.schema_sql
    shared_from = (
        f"from {schema_sql}.user_playlist_shares s "
        f"join {schema_sql}.user_playlists p on p.id = s.playlist_id "
        f"join {schema_sql}.profiles owner on owner.id = p.user_id "
        f"where s.user_id = $1 and p.user_id <> $1 "
        f"and p.deleted_at is null"
    )

    total_row = await db.fetchrow(
        f"select count(*) as total {shared_from}", viewer
    )
    total = int(total_row["total"]) if total_row is not None else 0

    rows = await db.fetch(
        f"select {_playlist_columns(schema_sql)}, owner.email as owner_email "
        f"{shared_from} "
        f"order by p.updated_at desc, p.id desc limit $2 offset $3",
        viewer,
        limit,
        offset,
    )
    return [
        {**dict(row), "is_owner": False} for row in rows
    ], total


async def get_accessible_playlist_with_tracks(
    db: Database,
    playlist_id: str | UUID,
    viewer_id: str | UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool] | None:
    """Return a playlist the viewer owns or that was shared with them.

    Shared viewers read the *owner's* visible ``user_tracks``; a playlist that
    is missing, soft-deleted, or neither owned nor shared returns ``None``. The
    playlist dict always includes ``owner_email`` and ``is_owner``.
    """
    identifier = _as_uuid(playlist_id)
    viewer = _as_uuid(viewer_id)
    schema_sql = db.schema_sql
    record = await db.fetchrow(
        f"select {_playlist_columns(schema_sql)}, "
        f"owner.email as owner_email, (p.user_id = $2) as is_owner "
        f"from {schema_sql}.user_playlists p "
        f"join {schema_sql}.profiles owner on owner.id = p.user_id "
        f"where p.id = $1 and p.deleted_at is null "
        f"and (p.user_id = $2 or exists ("
        f"select 1 from {schema_sql}.user_playlist_shares s "
        f"where s.playlist_id = p.id and s.user_id = $2))",
        identifier,
        viewer,
    )
    if record is None:
        return None

    playlist = dict(record)
    playlist["is_owner"] = bool(
        playlist.get("is_owner", playlist["user_id"] == viewer)
    )
    playlist.setdefault("owner_email", "")
    identifiers = await list_track_ids(db, playlist["id"])
    items = await tracks.list_tracks_by_ids(
        db, playlist["user_id"], identifiers
    )
    return playlist, items, playlist["is_owner"]


async def list_playlist_shares(
    db: Database,
    playlist_id: str | UUID,
    owner_id: str | UUID,
) -> list[dict[str, Any]]:
    """Return the accounts a playlist is shared with (owner only).

    Raises :class:`UserPlaylistNotFoundError` when the playlist is missing,
    soft-deleted, or owned by somebody else, which the router maps to a 404.
    """
    playlist = await get_user_playlist(db, playlist_id, owner_id)
    if playlist is None:
        raise UserPlaylistNotFoundError("Playlist not found.")
    rows = await db.fetch(
        f"select s.user_id, p.email, s.created_at "
        f"from {db.schema_sql}.user_playlist_shares s "
        f"join {db.schema_sql}.profiles p on p.id = s.user_id "
        f"where s.playlist_id = $1 "
        f"order by s.created_at desc, p.email asc",
        playlist["id"],
    )
    return [dict(row) for row in rows]


async def share_playlist_with_email(
    db: Database,
    playlist_id: str | UUID,
    owner_id: str | UUID,
    email: str,
) -> dict[str, Any]:
    """Share an owned playlist with another approved account.

    The owner check happens first so a non-owner always sees the same 404 as a
    missing playlist. Unknown, unapproved, and self addresses raise
    :class:`ShareRecipientError` with one generic message; repeating a share is
    idempotent and returns the existing row.
    """
    playlist = await get_user_playlist(db, playlist_id, owner_id)
    if playlist is None:
        raise UserPlaylistNotFoundError("Playlist not found.")

    candidate = email.strip() if isinstance(email, str) else ""
    target = None
    if candidate:
        target = await db.fetchrow(
            f"select id, email, is_approved from {db.schema_sql}.profiles "
            f"where lower(email) = lower($1)",
            candidate,
        )
    if (
        target is None
        or not bool(target["is_approved"])
        or target["id"] == playlist["user_id"]
    ):
        raise ShareRecipientError("That account cannot be added.")

    schema_sql = db.schema_sql
    record = await db.fetchrow(
        f"insert into {schema_sql}.user_playlist_shares "
        f"(playlist_id, user_id) values ($1, $2) "
        f"on conflict (playlist_id, user_id) do nothing "
        f"returning user_id, created_at",
        playlist["id"],
        target["id"],
    )
    if record is None:
        record = await db.fetchrow(
            f"select user_id, created_at from "
            f"{schema_sql}.user_playlist_shares "
            f"where playlist_id = $1 and user_id = $2",
            playlist["id"],
            target["id"],
        )
    if record is None:  # pragma: no cover - the row was just inserted
        raise RuntimeError("Playlist share insert returned no row.")
    return {
        "user_id": record["user_id"],
        "email": target["email"],
        "created_at": record["created_at"],
    }


async def unshare_playlist(
    db: Database,
    playlist_id: str | UUID,
    owner_id: str | UUID,
    target_user_id: str | UUID,
) -> bool:
    """Remove a share (owner only); ``False`` when it was not shared."""
    playlist = await get_user_playlist(db, playlist_id, owner_id)
    if playlist is None:
        raise UserPlaylistNotFoundError("Playlist not found.")
    removed = await db.fetchrow(
        f"delete from {db.schema_sql}.user_playlist_shares "
        f"where playlist_id = $1 and user_id = $2 "
        f"returning user_id",
        playlist["id"],
        _as_uuid(target_user_id),
    )
    return removed is not None


async def _lock_playlist(
    connection: Any,
    schema_sql: str,
    playlist_id: UUID,
    user_id: UUID,
) -> None:
    """Verify ownership and serialize membership changes for this playlist."""
    record = await connection.fetchrow(
        f"select p.id from {schema_sql}.user_playlists p "
        f"where p.id = $1 and p.user_id = $2 and p.deleted_at is null "
        f"for update",
        playlist_id,
        user_id,
    )
    if record is None:
        raise UserPlaylistNotFoundError("Playlist not found.")


async def add_track(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
    track_id: str | UUID,
) -> None:
    """Append one of the caller's visible tracks; already-present is a no-op."""
    identifier = _as_uuid(playlist_id)
    owner = _as_uuid(user_id)
    track = _as_uuid(track_id)
    schema_sql = db.schema_sql

    async with db.transaction() as connection:
        await _lock_playlist(connection, schema_sql, identifier, owner)

        visible = await connection.fetchrow(
            f"select ut.id from {schema_sql}.user_tracks ut "
            f"join {schema_sql}.media_assets a on a.id = ut.asset_id "
            f"where ut.id = $1 and ut.user_id = $2 "
            f"and {_visible_track_predicate(schema_sql)}",
            track,
            owner,
        )
        if visible is None:
            raise UserPlaylistTrackNotFoundError("Track not found.")

        await connection.execute(
            f"insert into {schema_sql}.user_playlist_tracks "
            f"(playlist_id, user_track_id, position) "
            f"select $1, $2, coalesce(max(t.position) + 1, 0) "
            f"from {schema_sql}.user_playlist_tracks t "
            f"where t.playlist_id = $1 "
            f"on conflict (playlist_id, user_track_id) do nothing",
            identifier,
            track,
        )
        await connection.execute(
            f"update {schema_sql}.user_playlists "
            f"set updated_at = now() where id = $1 and user_id = $2",
            identifier,
            owner,
        )


async def remove_track(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
    track_id: str | UUID,
) -> bool:
    """Remove a track and compact the remaining positions to ``0..n-1``."""
    identifier = _as_uuid(playlist_id)
    owner = _as_uuid(user_id)
    track = _as_uuid(track_id)
    schema_sql = db.schema_sql

    async with db.transaction() as connection:
        await _lock_playlist(connection, schema_sql, identifier, owner)

        removed = await connection.fetchrow(
            f"delete from {schema_sql}.user_playlist_tracks "
            f"where playlist_id = $1 and user_track_id = $2 "
            f"returning position",
            identifier,
            track,
        )
        if removed is None:
            return False

        await connection.execute(
            f"update {schema_sql}.user_playlist_tracks t "
            f"set position = ranked.rn "
            f"from (select s.user_track_id, "
            f"row_number() over (order by s.position) - 1 as rn "
            f"from {schema_sql}.user_playlist_tracks s "
            f"where s.playlist_id = $1) ranked "
            f"where t.playlist_id = $1 "
            f"and t.user_track_id = ranked.user_track_id "
            f"and t.position <> ranked.rn",
            identifier,
        )
        await connection.execute(
            f"update {schema_sql}.user_playlists "
            f"set updated_at = now() where id = $1 and user_id = $2",
            identifier,
            owner,
        )
    return True


async def reorder_tracks(
    db: Database,
    playlist_id: str | UUID,
    user_id: str | UUID,
    track_ids: Iterable[str | UUID],
) -> None:
    """Rewrite the playlist's positions to exactly ``track_ids`` order.

    ``track_ids`` must be a permutation of the current membership; anything
    else raises :class:`InvalidTrackOrderError`. All position updates run in
    one transaction, which the deferred unique constraint makes safe.
    """
    identifier = _as_uuid(playlist_id)
    owner = _as_uuid(user_id)
    ordered = [_as_uuid(value) for value in track_ids]
    schema_sql = db.schema_sql

    async with db.transaction() as connection:
        await _lock_playlist(connection, schema_sql, identifier, owner)

        rows = await connection.fetch(
            f"select t.user_track_id from "
            f"{schema_sql}.user_playlist_tracks t "
            f"where t.playlist_id = $1 for update",
            identifier,
        )
        current = [row["user_track_id"] for row in rows]
        if len(ordered) != len(current) or set(ordered) != set(current):
            raise InvalidTrackOrderError(
                "Track order must contain every playlist track exactly once."
            )

        for position, track in enumerate(ordered):
            await connection.execute(
                f"update {schema_sql}.user_playlist_tracks "
                f"set position = $3 "
                f"where playlist_id = $1 and user_track_id = $2",
                identifier,
                track,
                position,
            )
        await connection.execute(
            f"update {schema_sql}.user_playlists "
            f"set updated_at = now() where id = $1 and user_id = $2",
            identifier,
            owner,
        )
