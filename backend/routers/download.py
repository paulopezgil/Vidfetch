"""Download submission endpoint."""
from __future__ import annotations

from fastapi import APIRouter, status

from ..models.schemas import DownloadRequest
from ..services.task_manager import manager

router = APIRouter(tags=["download"])


@router.post("/api/download", status_code=status.HTTP_202_ACCEPTED)
async def create_download(req: DownloadRequest) -> dict:
    """Start a download task and return its id for progress monitoring."""
    task_id = manager.create_task(
        url=req.url,
        operation_type=req.operation_type,
        format=req.format,
        embed_subs=req.embed_subs,
        playlist_id=req.playlist_id,
    )
    return {"task_id": task_id}
