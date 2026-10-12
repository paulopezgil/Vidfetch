"""Application configuration loaded from environment variables.

All paths and tunables are read from the environment so the same code runs
locally (``uvicorn backend.main:app``) and inside Docker without changes.
"""
from __future__ import annotations

import os
from pathlib import Path


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    path = Path(raw).expanduser() if raw else default
    return path.resolve()


class Settings:
    def __init__(self) -> None:
        base = Path.cwd()

        # Persistent media + metadata storage.
        self.download_dir = _path_from_env("DOWNLOAD_DIR", base / "downloads")
        self.data_dir = _path_from_env("DATA_DIR", base / "data")
        self.db_path = _path_from_env("DB_PATH", self.data_dir / "yt-dlp.db")

        # Hidden working directories (excluded from the library listing).
        self.tmp_dir = self.download_dir / ".tmp"
        self.thumb_dir = self.download_dir / ".thumbnails"

        # Resource limits.
        self.max_concurrent_downloads = int(
            os.getenv("MAX_CONCURRENT_DOWNLOADS", "2")
        )

        # Refuse to start a download when the target filesystem has less than
        # this much free space. This is a coarse floor, not a size estimate.
        self.min_free_disk_mb = int(os.getenv("MIN_FREE_DISK_MB", "500"))

        cors_raw = os.getenv("CORS_ORIGINS", "*")
        self.cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()]

        # Where the built frontend lives (Docker copies it here). Optional: if
        # absent the backend runs API-only (the Vite dev server proxies to it).
        self.frontend_dist = _path_from_env("FRONTEND_DIST", base / "frontend-dist")

    def ensure_directories(self) -> None:
        for directory in (
            self.download_dir,
            self.data_dir,
            self.tmp_dir,
            self.thumb_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
