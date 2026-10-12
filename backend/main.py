"""FastAPI application entry point."""
from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database
from .config import settings
from .routers import download, files, health, history, info, playlists, tasks

logger = logging.getLogger("yt-dlp-frontend")

APP_VERSION = "1.0.0"


def _log_dependencies() -> None:
    node = shutil.which("node")
    ffmpeg = shutil.which("ffmpeg")
    if not node:
        logger.warning(
            "Node.js runtime not found on PATH. yt-dlp may require it for some "
            "YouTube downloads. Install Node.js and ensure it is on PATH."
        )
    if not ffmpeg:
        logger.warning(
            "FFmpeg not found on PATH. Audio extraction and media merging "
            "will not work. Install FFmpeg."
        )
    logger.info(
        "Dependencies: node=%s, ffmpeg=%s", node or "MISSING", ffmpeg or "MISSING"
    )


def _recover_stale_tasks() -> None:
    database.mark_interrupted_tasks()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    _recover_stale_tasks()
    _log_dependencies()
    yield


app = FastAPI(
    title="yt-dlp Frontend",
    version=APP_VERSION,
    lifespan=lifespan,
)

allow_credentials = "*" not in settings.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(info.router)
app.include_router(download.router)
app.include_router(tasks.router)
app.include_router(files.router)
app.include_router(history.router)
app.include_router(playlists.router)
app.include_router(health.router)


# -- Serve the built frontend (when present, e.g. inside Docker) ------------ #

_dist = settings.frontend_dist
if _dist.exists():
    assets = _dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
else:  # pragma: no cover - local development without a built frontend
    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "app": "yt-dlp-frontend",
            "message": "API is running. Serve the Vite dev server for the UI.",
            "docs": "/docs",
        }
