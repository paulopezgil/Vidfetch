"""Health and dependency status endpoint."""
from __future__ import annotations

import platform
import shutil
import subprocess

from fastapi import APIRouter

from ..models.schemas import HealthOut

router = APIRouter(tags=["health"])

APP_VERSION = "1.0.0"


def _command_version(cmd: str, *args: str) -> str | None:
    executable = shutil.which(cmd)
    if not executable:
        return None
    try:
        proc = subprocess.run(
            [executable, *args], capture_output=True, text=True, timeout=10
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip().splitlines()[0].strip() if proc.stdout else None


def _ytdlp_version() -> str | None:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return None


@router.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    node_version = _command_version("node", "--version")
    ffmpeg_version = _command_version("ffmpeg", "-version")
    return HealthOut(
        status="ok",
        version=APP_VERSION,
        ytdlp_version=_ytdlp_version(),
        python_version=platform.python_version(),
        dependencies={
            "node_available": node_version is not None,
            "node_version": node_version,
            "ffmpeg_available": ffmpeg_version is not None,
            "ffmpeg_version": ffmpeg_version,
        },
    )
