"""FastAPI application factory for the v2 backend.

Nothing here connects to the network, a database, or the filesystem at import
time. The pool is created in the lifespan, which also ensures the media storage
directories exist. ``app`` is exported for ``uvicorn backend.app.main:app``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..version import APP_VERSION
from .api.errors import ApiError, register_exception_handlers
from .api.routes import admin, downloads, health, me
from .core.config import Settings
from .core.db import create_pool
from .services.storage import Storage
from .services.worker import Worker
API_PREFIX = "api"


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


def _add_spa_routes(app: FastAPI, frontend_dist) -> None:
    """Serve the built SPA when present, without shadowing ``/api``."""
    dist = frontend_dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path == API_PREFIX or full_path.startswith(f"{API_PREFIX}/"):
            raise ApiError(404, "not_found", "Not found.")

        candidate = (dist / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and (candidate == dist or dist in candidate.parents)
        ):
            return FileResponse(candidate)

        index = dist / "index.html"
        if not index.is_file():
            raise ApiError(404, "not_found", "Not found.")
        return FileResponse(index)


def _add_root_json_route(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "app": "vidfetch",
            "message": "API is running. Serve the Vite dev server for the UI.",
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

    # A wildcard origin is public by definition; never combine it with
    # credentials. Explicit origins may use credentialed requests.
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

    frontend_dist = resolved.frontend_dist
    if frontend_dist.is_dir():
        _add_spa_routes(app, frontend_dist)
    else:
        _add_root_json_route(app)

    return app


app = create_app()
