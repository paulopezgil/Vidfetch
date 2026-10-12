"""Playlist detail, deletion, and on-demand ZIP download endpoints."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .. import database
from ..config import settings
from ..models.schemas import PlaylistDetailOut
from ..services import library, zip_service
from ..services.filenames import sanitize_filename

router = APIRouter(tags=["playlists"])


@router.get("/api/playlists/{playlist_id}", response_model=PlaylistDetailOut)
async def get_playlist(playlist_id: str) -> dict:
    detail = library.playlist_detail(playlist_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Playlist not found.")
    return detail


@router.delete("/api/playlists/{playlist_id}")
async def delete_playlist(playlist_id: str) -> dict:
    """Delete a playlist and its item files. History is kept.

    No archive is persisted, so there is no ZIP to remove.
    """
    playlist = database.get_playlist(playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found.")

    deleted_files = 0
    for item in database.get_playlist_items(playlist_id):
        if item.get("filename"):
            (settings.download_dir / item["filename"]).unlink(missing_ok=True)
            deleted_files += 1

    database.delete_playlist(playlist_id)
    return {"playlist_id": playlist_id, "deleted": True, "files_deleted": deleted_files}


@router.get("/api/playlists/{playlist_id}/zip")
async def download_playlist_zip(playlist_id: str) -> FileResponse:
    """Build and stream a ZIP of the playlist's currently-downloaded items.

    The archive is generated fresh on every request from the item rows whose
    status is ``downloaded`` *and* whose file exists right now, so a failed item
    that was later retried is included automatically. It is built into a hidden
    temporary file under ``settings.tmp_dir`` and deleted once the response has
    been sent: nothing is persisted under ``settings.download_dir``.
    """
    playlist = database.get_playlist(playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found.")

    files = [
        settings.download_dir / item["filename"]
        for item in database.get_playlist_items(playlist_id)
        if item["status"] == "downloaded" and item.get("filename")
        and (settings.download_dir / item["filename"]).is_file()
    ]
    if not files:
        raise HTTPException(status_code=409, detail="No downloaded files to package.")

    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".playlist_zip_", suffix=".zip", dir=str(settings.tmp_dir)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        await asyncio.to_thread(zip_service.create_zip, files, tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    filename = f"{sanitize_filename(playlist['title'])} [{playlist_id}].zip"
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=filename,
        content_disposition_type="attachment",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )
