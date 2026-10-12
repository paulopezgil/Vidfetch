"""Metadata inspection endpoint."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..models.schemas import InfoRequest
from ..services import ytdlp_service

router = APIRouter(tags=["info"])


@router.post("/api/info")
async def get_info(req: InfoRequest) -> dict:
    """Return normalised metadata for a video or playlist URL.

    Only metadata is fetched; no media is downloaded.
    """
    try:
        info = await asyncio.to_thread(ytdlp_service.get_info, req.url)
    except ytdlp_service.DownloadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return info
