"""Owner-scoped track metadata, autocomplete facets, and cover art.

Tracks are per-user rows over the shared media cache. Rows are created by the
database trigger when a download becomes ready; this router lets the owner
rename a track, discover existing artist/album names, and attach their own
cover image.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from ...core.config import Settings
from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import (
    CoverOut,
    CoverUpload,
    FacetItem,
    FacetList,
    ProfileOut,
    TrackList,
    TrackOut,
    TrackUpdate,
)
from ...services import tracks
from ...services.signing import MediaTokenError, sign_media_token, verify_media_token
from ...services.storage import Storage
from ..deps import get_db, get_settings, get_storage, require_approved
from ..errors import ApiError

router = APIRouter(tags=["tracks"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "track_not_found", "Track not found.")


def _cover_missing() -> ApiError:
    return ApiError(404, "cover_not_found", "Cover image not found.")


def _invalid_metadata() -> ApiError:
    return ApiError(400, "invalid_request", "Invalid track metadata.")


def _invalid_query() -> ApiError:
    return ApiError(400, "invalid_request", "Invalid request parameters.")


def _public_url(settings: Settings, path: str) -> str:
    """Prefix an API path with ``PUBLIC_API_URL`` when one is configured."""
    return f"{settings.public_api_url}{path}" if settings.public_api_url else path


def _cover_url(
    settings: Settings,
    user_id: UUID,
    track: dict,
) -> str | None:
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


def _thumbnail_url(
    settings: Settings,
    user_id: UUID,
    track: dict,
) -> str | None:
    """Build a signed thumbnail URL bound to the viewer's account."""
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
    user_id: UUID,
    row: dict,
) -> TrackOut:
    data = dict(row)
    data["cover_url"] = _cover_url(settings, user_id, data)
    data["thumbnail_url"] = _thumbnail_url(settings, user_id, data)
    return TrackOut.model_validate(data)


@router.get("/api/tracks", response_model=TrackList)
async def list_tracks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
    sort: Literal["downloaded", "title"] = Query(default="downloaded"),
    kind: Literal["audio", "video", "image"] | None = Query(default=None),
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> TrackList:
    """List the caller's visible tracks.

    ``sort=downloaded`` (default) is newest download first; ``sort=title`` is
    alphabetical by the resolved title the client displays. ``kind`` keeps only
    audio, video, or image tracks (by output extension) so the Songs and Videos
    views page over their own media kind instead of filtering a mixed page.
    """
    if db is None:
        raise _unavailable()
    try:
        rows, total = await tracks.list_tracks(
            db,
            profile.id,
            limit=limit,
            offset=offset,
            q=q,
            sort=sort,
            kind=kind,
        )
    except ValueError as exc:
        raise _invalid_query() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return TrackList(
        items=[_track_out(settings, profile.id, row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/tracks/artists", response_model=FacetList)
async def list_artists(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> FacetList:
    """Return the caller's distinct artist names for autocomplete."""
    return await _list_facets(db, profile.id, kind="artist", q=q, limit=limit)


@router.get("/api/tracks/albums", response_model=FacetList)
async def list_albums(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> FacetList:
    """Return the caller's distinct album names for autocomplete."""
    return await _list_facets(db, profile.id, kind="album", q=q, limit=limit)


async def _list_facets(
    db: Database | None,
    user_id: UUID,
    *,
    kind: str,
    q: str | None,
    limit: int,
) -> FacetList:
    if db is None:
        raise _unavailable()
    try:
        rows = await tracks.list_facets(
            db, user_id, kind=kind, q=q, limit=limit
        )
    except ValueError as exc:
        raise _invalid_metadata() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return FacetList(items=[FacetItem.model_validate(row) for row in rows])


@router.patch("/api/tracks/{track_id}", response_model=TrackOut)
async def update_track(
    track_id: UUID,
    payload: TrackUpdate,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> TrackOut:
    """Update only the provided metadata fields on the caller's own track."""
    if db is None:
        raise _unavailable()
    fields = payload.model_dump(exclude_unset=True)
    try:
        row = await tracks.update_track(db, track_id, profile.id, fields)
    except ValueError as exc:
        raise _invalid_metadata() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    return _track_out(settings, profile.id, row)


@router.post("/api/tracks/{track_id}/cover", response_model=CoverOut)
async def upload_cover(
    track_id: UUID,
    payload: CoverUpload,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> CoverOut:
    """Store a validated cover image for the caller's track."""
    if db is None:
        raise _unavailable()
    try:
        relative = await tracks.set_cover(
            db,
            storage,
            track_id,
            profile.id,
            content_type=payload.content_type,
            data=payload.data,
        )
    except tracks.CoverValidationError as exc:
        raise ApiError(400, "invalid_cover", str(exc)) from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if relative is None:
        raise _not_found()
    return CoverOut(
        cover_path=relative,
        cover_url=_cover_url(
            settings,
            profile.id,
            {"id": track_id, "cover_path": relative},
        )
        or "",
    )


@router.delete(
    "/api/tracks/{track_id}/cover",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_cover(
    track_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Remove the caller's cover image and clear the stored path."""
    if db is None:
        raise _unavailable()
    try:
        deleted = await tracks.delete_cover(
            db, storage, track_id, profile.id
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/covers/{track_id}")
async def stream_cover(
    track_id: UUID,
    token: str = Query(min_length=1),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileResponse:
    """Serve a track cover authorized by a signed token (no Bearer header)."""
    claims = verify_media_token(token, settings.media_token_secret)
    if claims.asset_id != f"cover:{track_id}":
        raise MediaTokenError("invalid_token", "Invalid media token.")
    if db is None:
        raise _unavailable()
    try:
        path = await tracks.resolve_cover_path(
            db, storage, track_id, claims.user_id
        )
    except ValueError as exc:
        raise MediaTokenError("invalid_token", "Invalid media token.") from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if path is None:
        raise _cover_missing()
    return FileResponse(
        path,
        media_type=tracks.cover_media_type(path),
        headers={"Cache-Control": "private, max-age=3600"},
    )
