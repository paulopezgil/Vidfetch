"""Pydantic request and response models."""
from __future__ import annotations

from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

OperationType = Literal["video", "playlist", "playlist_item"]
FormatName = Literal["best", "720p", "mp3"]


def validate_url(value: str) -> str:
    """Validate that a URL is a plausible http(s) URL and return it stripped."""
    value = (value or "").strip()
    if not value:
        raise ValueError("URL is required.")
    try:
        parsed = urlparse(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("Malformed URL.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a valid http(s) URL.")
    return value


class InfoRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_url(v)


class DownloadRequest(BaseModel):
    url: str
    operation_type: OperationType = "video"
    format: FormatName = "best"
    embed_subs: bool = False
    playlist_id: str = ""

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return validate_url(v)


class RebuildZipRequest(BaseModel):
    force: bool = False


class TaskOut(BaseModel):
    task_id: str
    url: str
    title: str = ""
    video_id: str = ""
    operation_type: str
    format: str = "best"
    embed_subs: bool = False
    status: str
    progress: float = 0
    current_item_progress: float = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0
    eta: float = 0
    item_index: int = 0
    item_count: int = 0
    completed_items: int = 0
    current_item_title: str = ""
    playlist_id: str = ""
    output_filename: str = ""
    error: str = ""
    created_at: str
    updated_at: str
    completed_at: str = ""


class HealthOut(BaseModel):
    status: str
    version: str
    ytdlp_version: Optional[str] = None
    python_version: str
    dependencies: dict[str, Any]


class LibraryFile(BaseModel):
    filename: str
    title: str
    size: int
    mtime: float
    ext: str
    media_type: str
    thumbnail_url: Optional[str] = None
    video_id: str = ""
    playlist_id: str = ""


class PlaylistItemOut(BaseModel):
    index: int
    video_id: str
    url: str
    title: str
    duration: Optional[float] = None
    status: str
    filename: str = ""
    size: int = 0
    error: str = ""


class PlaylistOut(BaseModel):
    playlist_id: str
    url: str = ""
    title: str
    channel: str = ""
    thumbnail_url: Optional[str] = None
    item_count: int = 0
    total_size: int = 0
    zip_path: str = ""
    status: str
    created_at: str
    updated_at: str


class PlaylistDetailOut(PlaylistOut):
    items: list[PlaylistItemOut] = []
    downloaded_count: int = 0
    failed_count: int = 0


class HistoryEntry(TaskOut):
    file_exists: bool = False


class HistoryPage(BaseModel):
    items: list[HistoryEntry]
    total: int
    limit: int
    offset: int
