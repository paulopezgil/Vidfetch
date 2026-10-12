"""Playlist detail, deletion, and ZIP rebuild endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import database
from ..config import settings
from ..models.schemas import PlaylistDetailOut, RebuildZipRequest
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
    """Delete a playlist, its item files, and its ZIP. History is kept."""
    playlist = database.get_playlist(playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found.")

    deleted_files = 0
    for item in database.get_playlist_items(playlist_id):
        if item.get("filename"):
            (settings.download_dir / item["filename"]).unlink(missing_ok=True)
            deleted_files += 1
    if playlist.get("zip_path"):
        (settings.download_dir / playlist["zip_path"]).unlink(missing_ok=True)
        deleted_files += 1

    database.delete_playlist(playlist_id)
    return {"playlist_id": playlist_id, "deleted": True, "files_deleted": deleted_files}


@router.post("/api/playlists/{playlist_id}/zip")
async def rebuild_zip(playlist_id: str, req: RebuildZipRequest) -> dict:
    """(Re)build the ZIP archive for a playlist's downloaded items."""
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

    zip_name = f"{sanitize_filename(playlist['title'])} [{playlist_id}].zip"
    zip_path = settings.download_dir / zip_name
    if zip_path.exists() and not req.force:
        return {"playlist_id": playlist_id, "zip_path": zip_name, "built": False}

    await asyncio.to_thread(zip_service.create_zip, files, zip_path)
    database.upsert_playlist({
        **playlist,
        "zip_path": zip_name,
        "updated_at": database.iso_now(),
    })
    return {"playlist_id": playlist_id, "zip_path": zip_name, "built": True}
