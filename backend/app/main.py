"""FastAPI application factory for the v2 backend.

Nothing here connects to the network, a database, or the filesystem at import
time. The pool is created in the lifespan, which also ensures the media storage
directories exist. ``app`` is exported for ``uvicorn backend.app.main:app``.

The backend is a pure JSON/media API: the UI is a separately deployed app
(Vite dev server locally, Vercel in production). Only ``/`` returns a small
diagnostic payload; everything user-facing lives under ``/api``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..version import APP_VERSION
from .api.errors import register_exception_handlers
from .api.routes import admin, downloads, health, library, media, me, playlists
from .core.config import Settings
from .core.db import create_pool
from .services.storage import Storage
from .services.worker import Worker


def _create_lifespan(resolved: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Tests deliberately run without a real environment; everything else
        # must fail fast with a clear configuration error.
        if resolved.environment != "test":
            resolved.validate_runtime()

        app.state.storage.ensure_directories()

        db = None
        if resolved.database_url:
            db = await create_pool(resolved)
        app.state.db = db

        # The worker owns the yt-dlp queue. Tests run with environment="test"
        # and no worker so they never spawn background downloads.
        worker = None
        if db is not None and resolved.environment != "test":
            worker = Worker(resolved, db, app.state.storage)
            await worker.start()
        app.state.worker = worker

        try:
            yield
        finally:
            if worker is not None:
                await worker.stop()
            app.state.worker = None
            if db is not None:
                await db.close()
            app.state.db = None

    return lifespan


def _add_root_json_route(app: FastAPI) -> None:
    """Small diagnostic payload; the UI lives in its own frontend service."""

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "app": "vidfetch",
            "version": APP_VERSION,
            "message": "Vidfetch API. The web UI is served by the frontend app.",
            "docs": "/docs",
        }


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the v2 application. Pass ``settings`` in tests; otherwise env."""
    resolved = settings or Settings.from_env()

    app = FastAPI(
        title="Vidfetch",
        version=APP_VERSION,
        lifespan=_create_lifespan(resolved),
    )
    app.state.settings = resolved
    app.state.storage = Storage(resolved.download_dir)
    app.state.db = None
    app.state.worker = None

    register_exception_handlers(app)

    # CORS: the browser UI is a separate origin. Local development uses the
    # Vite dev server (http://localhost:5173); production uses the deployed
    # Vercel origin. Origins stay explicit so credentialed (Bearer) requests
    # are only allowed from known sites. A wildcard origin is public by
    # definition, so it is never combined with credentials.
    wildcard = resolved.cors_origins == ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if wildcard else list(resolved.cors_origins),
        allow_credentials=not wildcard,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(downloads.router)
    app.include_router(library.router)
    app.include_router(media.router)
    app.include_router(playlists.router)

    _add_root_json_route(app)

    return app


app = create_app()
