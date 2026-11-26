"""Signed media and thumbnail streaming.

JSON endpoints use a Bearer token; browsers cannot attach that header to
``<video>``, ``<audio>``, ``<img>``, or plain download links. Media URLs are
therefore authorized by short-lived HMAC tokens bound to one asset and one
user. The streaming endpoints are public at the HTTP layer, but a valid token
and a still-approved profile are required for every request.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from ...core.config import Settings
from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import MediaTokenOut, ProfileOut
from ...services import assets, profiles
from ...services.signing import MediaTokenError, sign_media_token, verify_media_token
from ...services.storage import Storage, StorageError
from ..deps import get_db, get_settings, get_storage, require_approved
from ..errors import ApiError

router = APIRouter(tags=["media"])
_MEDIA_CACHE_HEADERS = {"Cache-Control": "private, no-store"}


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _asset_not_found() -> ApiError:
    return ApiError(404, "asset_not_found", "Media not found.")


def _asset_unavailable() -> ApiError:
    return ApiError(
        409,
        "asset_unavailable",
        "This media file is no longer available.",
    )


def _thumbnail_missing() -> ApiError:
    return ApiError(404, "thumbnail_not_found", "Thumbnail not found.")


def _resolve_media_path(
    storage: Storage, asset: dict, *, expected_size: int | None = None
) -> Path:
    """Resolve a stored relative media path without ever escaping the root."""
    relative = (asset.get("file_path") or "").strip()
    if not relative:
        raise StorageError("Media path is missing.")
    path = storage.validate_relative_path(relative)
    if path.is_symlink() or not path.is_file():
        raise StorageError("Media file is missing.")
    if expected_size is not None and path.stat().st_size != int(expected_size):
        raise StorageError("Media file size does not match.")
    return path


def _resolve_thumbnail_path(storage: Storage, asset: dict) -> Path:
    relative = (asset.get("thumbnail_path") or "").strip()
    if not relative:
        raise StorageError("Thumbnail path is missing.")
    path = storage.validate_relative_path(relative)
    if path.is_symlink() or not path.is_file():
        raise StorageError("Thumbnail file is missing.")
    return path


def _ready_asset_path(storage: Storage, asset: dict) -> Path:
    if asset.get("status") != "ready":
        raise _asset_unavailable()
    try:
        return _resolve_media_path(
            storage,
            asset,
            expected_size=asset.get("file_size_bytes"),
        )
    except (OSError, StorageError) as exc:
        raise _asset_unavailable() from exc


async def _approved_token_user(
    token: str,
    settings: Settings,
    db: Database | None,
):
    """Verify a media token and confirm its user is still approved."""
    claims = verify_media_token(token, settings.media_token_secret)
    if db is None:
        raise _unavailable()
    try:
        row = await profiles.get_profile(db, claims.user_id)
    except ValueError as exc:
        raise MediaTokenError("invalid_token", "Invalid media token.") from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if row is None or not bool(row.get("is_approved")):
        raise ApiError(
            403,
            "approval_required",
            "Your account is awaiting administrator approval.",
        )
    return claims


def _public_url(settings: Settings, path: str) -> str:
    """Prefix an API path with ``PUBLIC_API_URL`` when one is configured.

    Split deployments (frontend on Vercel, backend on a VPS) need absolute
    media links so the browser downloads straight from the backend. With no
    base URL the path stays relative, which keeps same-origin and test setups
    working unchanged.
    """
    base = settings.public_api_url
    return f"{base}{path}" if base else path


@router.post(
    "/api/media/{asset_id}/token",
    response_model=MediaTokenOut,
)
async def issue_media_token(
    asset_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> MediaTokenOut:
    """Issue short-lived signed URLs for a ready asset and its thumbnail."""
    if db is None:
        raise _unavailable()
    try:
        asset = await assets.get_asset(db, asset_id)
    except ValueError as exc:
        raise _asset_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if asset is None:
        raise _asset_not_found()

    _ready_asset_path(storage, asset)

    token = sign_media_token(
        settings.media_token_secret,
        str(asset_id),
        str(profile.id),
        settings.media_token_ttl_seconds,
    )
    try:
        claims = verify_media_token(token, settings.media_token_secret)
    except MediaTokenError as exc:  # pragma: no cover - defensive
        raise _unavailable() from exc

    expires_at = datetime.fromtimestamp(
        claims.expires_at, tz=timezone.utc
    )

    thumbnail_url: str | None = None
    try:
        _resolve_thumbnail_path(storage, asset)
    except (OSError, StorageError):
        thumbnail_url = None
    else:
        thumbnail_url = _public_url(
            settings, f"/api/thumbnails/{asset_id}?token={token}"
        )

    return MediaTokenOut(
        token=token,
        url=_public_url(settings, f"/api/media/{asset_id}?token={token}"),
        thumbnail_url=thumbnail_url,
        expires_at=expires_at,
        expires_in=settings.media_token_ttl_seconds,
    )


@router.get("/api/media/{asset_id}")
async def stream_media(
    asset_id: UUID,
    token: str = Query(min_length=1),
    download: int = Query(default=0, ge=0, le=1),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileResponse:
    """Stream a ready asset with HTTP range support."""
    claims = await _approved_token_user(token, settings, db)
    if claims.asset_id != str(asset_id):
        raise MediaTokenError("invalid_token", "Invalid media token.")

    try:
        asset = await assets.get_asset(db, asset_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _asset_not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if asset is None:
        raise _asset_not_found()

    path = _ready_asset_path(storage, asset)
    return FileResponse(
        path,
        filename=path.name,
        content_disposition_type="attachment" if download else "inline",
        headers=dict(_MEDIA_CACHE_HEADERS),
    )


@router.get("/api/thumbnails/{asset_id}")
async def stream_thumbnail(
    asset_id: UUID,
    token: str = Query(min_length=1),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileResponse:
    """Stream the thumbnail for a ready asset, if one exists."""
    claims = await _approved_token_user(token, settings, db)
    if claims.asset_id != str(asset_id):
        raise MediaTokenError("invalid_token", "Invalid media token.")

    try:
        asset = await assets.get_asset(db, asset_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _thumbnail_missing() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if asset is None:
        raise _thumbnail_missing()

    try:
        path = _resolve_thumbnail_path(storage, asset)
    except (OSError, StorageError) as exc:
        raise _thumbnail_missing() from exc
    return FileResponse(
        path,
        filename=path.name,
        content_disposition_type="inline",
        headers=dict(_MEDIA_CACHE_HEADERS),
    )
