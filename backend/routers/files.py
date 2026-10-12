"""Library listing, thumbnail serving, file download and deletion."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..services import library

router = APIRouter(tags=["files"])

_ALLOWED_THUMB_EXT = {".jpg", ".jpeg", ".png", ".webp"}


@router.get("/api/downloads")
async def get_downloads() -> dict:
    """Return the media library: individual files and playlist summaries."""
    return library.build_library()


@router.get("/api/thumb/{name}")
async def get_thumbnail(name: str) -> FileResponse:
    """Serve a stored thumbnail (images only, no path traversal)."""
    if Path(name).name != name:
        raise HTTPException(status_code=404, detail="Not found.")
    if Path(name).suffix.lower() not in _ALLOWED_THUMB_EXT:
        raise HTTPException(status_code=404, detail="Not found.")
    path = (settings.thumb_dir / name).resolve()
    if path.parent != settings.thumb_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


@router.get("/api/file/{filename}")
async def download_file(filename: str) -> FileResponse:
    """Stream a permitted output file as a download."""
    path = library.resolve_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="File not found.")
    media_type = _guess_type(path)
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="attachment",
    )


@router.delete("/api/file/{filename}")
async def delete_file(filename: str) -> dict:
    """Delete an output file after validation. History is preserved."""
    result = library.delete_file(filename)
    if result is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return result


def _guess_type(path: Path) -> Optional[str]:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
