"""Owner-scoped curated (user-created) playlists.

Unlike ``/api/playlists`` (downloaded source playlists), these are the caller's
own ordered collections of their per-user tracks. Every endpoint is scoped to
the authenticated, approved user; a playlist that is missing, soft-deleted, or
owned by somebody else is always a 404.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...core.config import Settings
from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import (
    ProfileOut,
    TrackOut,
    UserPlaylistAddTrack,
    UserPlaylistCreate,
    UserPlaylistDetailOut,
    UserPlaylistList,
    UserPlaylistOrder,
    UserPlaylistOut,
    UserPlaylistShareCreate,
    UserPlaylistShareList,
    UserPlaylistShareOut,
    UserPlaylistUpdate,
)
from ...services import user_playlists
from ...services.signing import sign_media_token
from ..deps import get_db, get_settings, require_approved
from ..errors import ApiError

router = APIRouter(prefix="/api/user-playlists", tags=["user-playlists"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _playlist_not_found() -> ApiError:
    return ApiError(404, "playlist_not_found", "Playlist not found.")


def _track_not_found() -> ApiError:
    return ApiError(404, "track_not_found", "Track not found.")


def _invalid_order() -> ApiError:
    return ApiError(
        400,
        "invalid_request",
        "Track order must contain every playlist track exactly once.",
    )


def _invalid_request() -> ApiError:
    return ApiError(400, "invalid_request", "Invalid playlist metadata.")


def _invalid_share_recipient() -> ApiError:
    return ApiError(
        400,
        "invalid_request",
        "That account cannot be added.",
    )


def _share_not_found() -> ApiError:
    return ApiError(404, "share_not_found", "Share not found.")


def _public_url(settings: Settings, path: str) -> str:
    """Prefix an API path with ``PUBLIC_API_URL`` when one is configured."""
    return f"{settings.public_api_url}{path}" if settings.public_api_url else path


def _cover_url(settings: Settings, user_id: UUID, track: dict) -> str | None:
    """Build a signed cover URL for a track that has a stored cover."""
    relative = str(track.get("cover_path") or "").strip()
    if not relative:
        return None
    track_id = track.get("id")
    token = sign_media_token(
        settings.media_token_secret,
        f"cover:{track_id}",
        str(user_id),
        settings.media_token_ttl_seconds,
    )
    return _public_url(settings, f"/api/covers/{track_id}?token={token}")


def _thumbnail_url(settings: Settings, user_id: UUID, track: dict) -> str | None:
    """Build a signed thumbnail URL bound to the viewer's approved account."""
    relative = str(track.get("thumbnail_path") or "").strip()
    asset_id = track.get("asset_id")
    if not relative or asset_id is None:
        return None
    token = sign_media_token(
        settings.media_token_secret,
        str(asset_id),
        str(user_id),
        settings.media_token_ttl_seconds,
    )
    return _public_url(settings, f"/api/thumbnails/{asset_id}?token={token}")


def _track_out(
    settings: Settings,
    viewer_id: UUID,
    row: dict,
    *,
    cover_user_id: UUID | None = None,
) -> TrackOut:
    data = dict(row)
    data["cover_url"] = _cover_url(
        settings, cover_user_id or viewer_id, data
    )
    data["thumbnail_url"] = _thumbnail_url(settings, viewer_id, data)
    return TrackOut.model_validate(data)


def _detail_out(
    settings: Settings,
    viewer_id: UUID,
    playlist: dict,
    items: list[dict],
    *,
    cover_user_id: UUID | None = None,
) -> UserPlaylistDetailOut:
    # Derive the count from the tracks that survived the visibility filter so
    # a detail response can never advertise more tracks than it contains (the
    # count and membership are separate queries and may straddle a change).
    #
    # A shared viewer reads the owner's tracks: cover tokens must name the
    # owner because ``/api/covers/{id}`` resolves the stored cover by the
    # token's user, while thumbnail tokens can stay bound to the viewer.
    return UserPlaylistDetailOut.model_validate(
        {
            **playlist,
            "track_count": len(items),
            "items": [
                _track_out(
                    settings,
                    viewer_id,
                    row,
                    cover_user_id=cover_user_id,
                )
                for row in items
            ],
        }
    )


@router.get("", response_model=UserPlaylistList)
async def list_user_playlists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistList:
    """List the caller's live curated playlists, newest updated first."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await user_playlists.list_user_playlists(
            db, profile.id, limit=limit, offset=offset
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return UserPlaylistList(
        items=[UserPlaylistOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserPlaylistOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_playlist(
    payload: UserPlaylistCreate,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistOut:
    """Create an empty curated playlist for the caller."""
    if db is None:
        raise _unavailable()
    try:
        row = await user_playlists.create_user_playlist(
            db,
            profile.id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        raise _invalid_request() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return UserPlaylistOut.model_validate(row)


@router.get("/shared", response_model=UserPlaylistList)
async def list_shared_user_playlists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistList:
    """List live playlists other accounts shared with the caller (read-only).

    This path is declared before ``/{playlist_id}`` so "shared" is never parsed
    as a playlist id.
    """
    if db is None:
        raise _unavailable()
    try:
        rows, total = await user_playlists.list_shared_with_user(
            db, profile.id, limit=limit, offset=offset
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return UserPlaylistList(
        items=[UserPlaylistOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{playlist_id}", response_model=UserPlaylistDetailOut)
async def get_user_playlist(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> UserPlaylistDetailOut:
    """Return a playlist the caller owns or that was shared with them."""
    if db is None:
        raise _unavailable()
    try:
        result = await user_playlists.get_accessible_playlist_with_tracks(
            db, playlist_id, profile.id
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if result is None:
        raise _playlist_not_found()
    playlist, items, _is_owner = result
    return _detail_out(
        settings,
        profile.id,
        playlist,
        items,
        cover_user_id=playlist["user_id"],
    )


@router.patch("/{playlist_id}", response_model=UserPlaylistOut)
async def update_user_playlist(
    playlist_id: UUID,
    payload: UserPlaylistUpdate,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistOut:
    """Update only the provided fields on the caller's playlist."""
    if db is None:
        raise _unavailable()
    fields = payload.model_dump(exclude_unset=True)
    try:
        row = await user_playlists.update_user_playlist(
            db, playlist_id, profile.id, fields
        )
    except ValueError as exc:
        raise _invalid_request() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if row is None:
        raise _playlist_not_found()
    return UserPlaylistOut.model_validate(row)


@router.delete(
    "/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_user_playlist(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> Response:
    """Soft-delete one of the caller's playlists."""
    if db is None:
        raise _unavailable()
    try:
        deleted = await user_playlists.delete_user_playlist(
            db, playlist_id, profile.id
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not deleted:
        raise _playlist_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{playlist_id}/tracks", response_model=UserPlaylistDetailOut
)
async def add_playlist_track(
    playlist_id: UUID,
    payload: UserPlaylistAddTrack,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> UserPlaylistDetailOut:
    """Append one of the caller's visible tracks (idempotent)."""
    if db is None:
        raise _unavailable()
    try:
        await user_playlists.add_track(
            db, playlist_id, profile.id, payload.track_id
        )
        result = await user_playlists.get_playlist_with_tracks(
            db, playlist_id, profile.id
        )
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except user_playlists.UserPlaylistTrackNotFoundError as exc:
        raise _track_not_found() from exc
    except ValueError as exc:
        raise _playlist_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if result is None:  # pragma: no cover - the playlist was just locked
        raise _playlist_not_found()
    playlist, items = result
    return _detail_out(settings, profile.id, playlist, items)


@router.put(
    "/{playlist_id}/tracks/order", response_model=UserPlaylistDetailOut
)
async def reorder_playlist_tracks(
    playlist_id: UUID,
    payload: UserPlaylistOrder,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> UserPlaylistDetailOut:
    """Reorder the playlist; ``track_ids`` must be an exact permutation."""
    if db is None:
        raise _unavailable()
    try:
        await user_playlists.reorder_tracks(
            db, playlist_id, profile.id, payload.track_ids
        )
        result = await user_playlists.get_playlist_with_tracks(
            db, playlist_id, profile.id
        )
    except user_playlists.InvalidTrackOrderError as exc:
        raise _invalid_order() from exc
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except ValueError as exc:
        raise _playlist_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if result is None:  # pragma: no cover - the playlist was just locked
        raise _playlist_not_found()
    playlist, items = result
    return _detail_out(settings, profile.id, playlist, items)


@router.delete(
    "/{playlist_id}/tracks/{track_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_playlist_track(
    playlist_id: UUID,
    track_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> Response:
    """Remove a track and compact the remaining positions."""
    if db is None:
        raise _unavailable()
    try:
        removed = await user_playlists.remove_track(
            db, playlist_id, profile.id, track_id
        )
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except ValueError as exc:
        raise _playlist_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not removed:
        raise _track_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{playlist_id}/shares", response_model=UserPlaylistShareList
)
async def list_playlist_shares(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistShareList:
    """List the accounts the caller shared this playlist with (owner only)."""
    if db is None:
        raise _unavailable()
    try:
        rows = await user_playlists.list_playlist_shares(
            db, playlist_id, profile.id
        )
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except ValueError as exc:
        raise _playlist_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return UserPlaylistShareList(
        items=[UserPlaylistShareOut.model_validate(row) for row in rows]
    )


@router.post(
    "/{playlist_id}/shares",
    response_model=UserPlaylistShareOut,
    status_code=status.HTTP_201_CREATED,
)
async def share_playlist(
    playlist_id: UUID,
    payload: UserPlaylistShareCreate,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> UserPlaylistShareOut:
    """Share the caller's playlist with another approved account."""
    if db is None:
        raise _unavailable()
    try:
        row = await user_playlists.share_playlist_with_email(
            db, playlist_id, profile.id, payload.email
        )
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except user_playlists.ShareRecipientError as exc:
        raise _invalid_share_recipient() from exc
    except ValueError as exc:
        raise _invalid_request() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return UserPlaylistShareOut.model_validate(row)


@router.delete(
    "/{playlist_id}/shares/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unshare_playlist(
    playlist_id: UUID,
    user_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> Response:
    """Remove a share from the caller's playlist (owner only)."""
    if db is None:
        raise _unavailable()
    try:
        removed = await user_playlists.unshare_playlist(
            db, playlist_id, profile.id, user_id
        )
    except user_playlists.UserPlaylistNotFoundError as exc:
        raise _playlist_not_found() from exc
    except ValueError as exc:
        raise _playlist_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not removed:
        raise _share_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
