"""Owner-scoped playlist listing, detail, deletion, and on-demand ZIP."""
from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ...core.config import Settings
from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import (
    PlaylistDetailOut,
    PlaylistList,
    PlaylistOut,
    ProfileOut,
)
from ...services import assets, playlists
from ...services.filenames import sanitize_filename
from ...services.signing import sign_media_token
from ...services.storage import Storage
from ..deps import get_db, get_settings, get_storage, require_approved
from ..errors import ApiError

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "playlist_not_found", "Playlist not found.")


def _empty_zip() -> ApiError:
    return ApiError(
        404,
        "playlist_empty",
        "This playlist has no downloadable files yet.",
    )


def _public_url(settings: Settings, path: str) -> str:
    """Prefix an API path with ``PUBLIC_API_URL`` when one is configured."""
    return f"{settings.public_api_url}{path}" if settings.public_api_url else path


def _item_thumbnail_url(
    settings: Settings,
    user_id: UUID,
    item: dict,
) -> str | None:
    """Build a signed thumbnail URL for an item whose asset has a thumbnail."""
    relative = str(item.get("asset_thumbnail_path") or "").strip()
    asset_id = item.get("asset_id")
    if not relative or asset_id is None:
        return None
    token = sign_media_token(
        settings.media_token_secret,
        str(asset_id),
        str(user_id),
        settings.media_token_ttl_seconds,
    )
    return _public_url(settings, f"/api/thumbnails/{asset_id}?token={token}")


def _item_out(settings: Settings, user_id: UUID, row: dict) -> dict:
    """Return an item mapping with a signed URL and no internal path."""
    data = dict(row)
    data.pop("asset_thumbnail_path", None)
    data["thumbnail_url"] = _item_thumbnail_url(settings, user_id, row)
    return data


@router.get("", response_model=PlaylistList)
async def list_playlists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> PlaylistList:
    """List the caller's playlists, newest first."""
    if db is None:
        raise _unavailable()
    try:
        rows, total = await playlists.list_playlists(
            db, profile.id, limit=limit, offset=offset
        )
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return PlaylistList(
        items=[PlaylistOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{playlist_id}", response_model=PlaylistDetailOut)
async def get_playlist(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlaylistDetailOut:
    """Return one of the caller's playlists with its items."""
    if db is None:
        raise _unavailable()
    try:
        row = await playlists.get_playlist(
            db, playlist_id, user_id=profile.id
        )
        if row is None:
            raise _not_found()
        items = await playlists.list_items_with_thumbnail_paths(
            db, playlist_id
        )
    except ValueError as exc:
        raise _not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return PlaylistDetailOut.model_validate(
        {
            **row,
            "items": [
                _item_out(settings, profile.id, item) for item in items
            ],
        }
    )


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
) -> Response:
    """Delete the caller's playlist rows. Shared media assets are retained."""
    if db is None:
        raise _unavailable()
    try:
        deleted = await playlists.delete_playlist(
            db, playlist_id, profile.id
        )
    except ValueError as exc:
        raise _not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    if not deleted:
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{playlist_id}/zip")
async def download_playlist_zip(
    playlist_id: UUID,
    profile: ProfileOut = Depends(require_approved),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> FileResponse:
    """Build and stream a temporary ZIP of the playlist's ready item files."""
    if db is None:
        raise _unavailable()
    try:
        playlist = await playlists.get_playlist(
            db, playlist_id, user_id=profile.id
        )
        if playlist is None:
            raise _not_found()
        items = await playlists.list_items(db, playlist_id)
    except ValueError as exc:
        raise _not_found() from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc

    candidates: list[tuple[str, Path]] = []
    for item in items:
        if item.get("status") != "ready" or item.get("asset_id") is None:
            continue
        try:
            asset = await assets.get_asset(db, item["asset_id"])
        except ValueError:
            continue
        except DB_UNAVAILABLE as exc:
            raise _unavailable() from exc
        if asset is None or asset.get("status") != "ready":
            continue
        relative = (asset.get("file_path") or "").strip()
        if not relative:
            continue
        try:
            path = storage.validate_relative_path(relative)
        except (OSError, ValueError):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        position = int(item.get("position") or len(candidates) + 1)
        title = sanitize_filename(
            item.get("title") or path.stem, max_len=100
        )
        arcname = f"{position:03d} - {title}{path.suffix.lower()}"
        candidates.append((arcname, path))

    if not candidates:
        raise _empty_zip()

    tmp_dir = storage.root / ".tmp"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - depends on filesystem
        raise _unavailable() from exc
    archive = tmp_dir / f"playlist-{playlist_id}-{uuid4().hex}.zip"

    try:
        await run_in_threadpool(_write_zip, archive, candidates)
    except (OSError, zipfile.BadZipFile) as exc:
        archive.unlink(missing_ok=True)
        raise _unavailable() from exc

    filename = f"{sanitize_filename(playlist.get('title') or 'playlist', 80)}.zip"
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(_remove_file, archive),
        headers={"Cache-Control": "private, no-store"},
    )


def _write_zip(archive: Path, entries: list[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED
    ) as handle:
        for arcname, path in entries:
            handle.write(path, arcname=arcname)


def _remove_file(path: Path) -> None:
    path.unlink(missing_ok=True)
