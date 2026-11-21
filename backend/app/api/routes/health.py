"""Public health endpoint.

Reports only coarse, non-sensitive state: versions, database reachability, auth
configuration, storage capacity, and external tool availability. No connection
strings, keys, user data, or signed URLs are included.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...core.config import Settings
from ...models.schemas import HealthOut, StorageHealth
from ....version import APP_VERSION
from ..deps import get_settings

router = APIRouter(tags=["health"])


def _yt_dlp_version() -> str | None:
    try:
        import yt_dlp

        return str(yt_dlp.version.__version__)
    except Exception:  # noqa: BLE001 - optional dependency
        return None


async def _database_reachable(db: Any) -> bool:
    if db is None:
        return False
    try:
        await db.fetchrow("select 1")
    except Exception:  # noqa: BLE001 - health must never raise
        return False
    return True


def _storage_health(storage: Any) -> StorageHealth:
    try:
        storage.ensure_directories()
        free_bytes = int(storage.free_bytes())
        writable = os.access(storage.root, os.W_OK)
    except Exception:  # noqa: BLE001 - report, do not crash health
        return StorageHealth(free_bytes=0, writable=False)
    return StorageHealth(free_bytes=free_bytes, writable=writable)


@router.get("/api/health", response_model=HealthOut)
async def health(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HealthOut:
    database = await _database_reachable(getattr(request.app.state, "db", None))
    storage = _storage_health(request.app.state.storage)
    auth_configured = bool(
        settings.supabase_jwt_secret or settings.supabase_jwks_url
    )

    if not storage.writable:
        status = "unavailable"
    elif not database:
        status = "degraded"
    else:
        status = "ok"

    return HealthOut(
        status=status,
        version=APP_VERSION,
        yt_dlp_version=_yt_dlp_version(),
        database=database,
        auth=auth_configured,
        storage=storage,
        dependencies={
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "node": shutil.which("node") is not None,
        },
    )
