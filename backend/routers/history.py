"""Persistent download history endpoint."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from .. import database
from ..config import settings
from ..models.schemas import HistoryEntry, HistoryPage

router = APIRouter(tags=["history"])

_ALLOWED_STATUS = {"completed", "failed", "cancelled"}


@router.get("/api/history", response_model=HistoryPage)
async def get_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    search: str | None = Query(None),
) -> HistoryPage:
    """Return persistent task history with filtering and pagination."""
    if status and status not in _ALLOWED_STATUS:
        status = None

    rows = database.list_tasks(limit=limit, offset=offset, status=status,
                               search=search)
    total = database.count_tasks(status=status)

    items: list[HistoryEntry] = []
    for row in rows:
        entry = dict(row)
        entry["embed_subs"] = bool(entry.get("embed_subs"))
        entry["file_exists"] = _file_exists(entry.get("output_filename") or "")
        items.append(HistoryEntry(**entry))

    return HistoryPage(items=items, total=total, limit=limit, offset=offset)


def _file_exists(filename: str) -> bool:
    if not filename:
        return False
    return (settings.download_dir / Path(filename).name).is_file()
