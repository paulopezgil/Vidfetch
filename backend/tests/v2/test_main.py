"""Tests for application assembly, the JSON root, CORS, and lifespan behavior."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigError
from backend.app import main as main_module
from backend.app.main import create_app
from backend.tests.v2.fakes import app_client, make_settings


def test_root_returns_json_diagnostics(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "vidfetch"
    assert body["docs"] == "/docs"
    assert body["version"]
    assert "frontend" in body["message"].lower()


def test_backend_does_not_serve_spa_routes(tmp_path, monkeypatch):
    # A stale frontend-dist directory (as left by the old all-in-one image)
    # must not turn the API into a static file server. Chdir into the fixture
    # so the old cwd-relative default would find it.
    monkeypatch.chdir(tmp_path)
    dist = tmp_path / "frontend-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-index</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        deep_link = client.get("/admin/users")
        asset = client.get("/assets/app.js")
        api = client.get("/api/health")
        unknown_api = client.get("/api/nope")

    assert deep_link.status_code == 404
    assert "spa-index" not in deep_link.text
    assert asset.status_code == 404
    assert api.status_code == 200
    assert api.json()["status"] == "degraded"
    assert unknown_api.status_code == 404
    assert unknown_api.json()["error"]["code"] == "not_found"


def test_cors_wildcard_does_not_allow_credentials(tmp_path):
    settings = make_settings(tmp_path, CORS_ORIGINS="*")

    with app_client(settings) as (app, client):
        response = client.get("/", headers={"Origin": "https://any.example.test"})

    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_cors_explicit_origin_allows_credentials(tmp_path):
    settings = make_settings(
        tmp_path, CORS_ORIGINS="https://app.example.test"
    )

    with app_client(settings) as (app, client):
        response = client.get(
            "/", headers={"Origin": "https://app.example.test"}
        )

    assert (
        response.headers["access-control-allow-origin"]
        == "https://app.example.test"
    )
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_preflight_allows_authorization_header(tmp_path):
    settings = make_settings(
        tmp_path, CORS_ORIGINS="http://localhost:5173"
    )

    with app_client(settings) as (app, client):
        response = client.options(
            "/api/me",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "http://localhost:5173"
    )
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed


def test_cors_unknown_origin_is_not_allowed(tmp_path):
    settings = make_settings(
        tmp_path, CORS_ORIGINS="https://app.example.test"
    )

    with app_client(settings) as (app, client):
        response = client.get(
            "/api/health", headers={"Origin": "https://evil.example.test"}
        )

    assert "access-control-allow-origin" not in response.headers


def test_non_test_environment_validates_configuration_on_startup(tmp_path):
    settings = make_settings(
        tmp_path,
        ENVIRONMENT="production",
        SUPABASE_JWT_SECRET="",
        SUPABASE_JWT_AUDIENCE="",
    )
    app = create_app(settings)

    with pytest.raises(ConfigError):
        with TestClient(app):
            pass


def test_lifespan_creates_and_closes_pool_when_database_configured(
    tmp_path, monkeypatch
):
    settings = make_settings(
        tmp_path, DATABASE_URL="postgresql://user:pass@pooler.example/db"
    )

    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    pool = FakePool()
    created: list = []

    async def fake_create_pool(settings):
        created.append(settings)
        return pool

    monkeypatch.setattr(main_module, "create_pool", fake_create_pool)

    with app_client(settings) as (app, client):
        assert app.state.db is pool
        assert app.state.worker is None
        assert created and created[0].database_url.startswith("postgresql://")

    assert pool.closed is True
    assert app.state.db is None


def test_lifespan_starts_and_stops_worker_outside_test_environment(
    tmp_path, monkeypatch
):
    settings = make_settings(
        tmp_path,
        ENVIRONMENT="production",
        DATABASE_URL="postgresql://user:pass@pooler.example/db",
        SUPABASE_URL="https://proj.supabase.co",
        MEDIA_TOKEN_SECRET="media-secret",
    )

    class FakePool:
        async def close(self) -> None:
            pass

    async def fake_create_pool(resolved):
        return FakePool()

    created: list = []

    class FakeWorker:
        def __init__(self, resolved, db, storage):
            self.started = False
            self.stopped = False
            self.storage = storage
            created.append(self)

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(main_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(main_module, "Worker", FakeWorker)

    with app_client(settings) as (app, client):
        worker = app.state.worker
        assert isinstance(worker, FakeWorker)
        assert worker.started is True
        assert worker.storage is app.state.storage

    assert worker.stopped is True
    assert app.state.worker is None


def test_lifespan_skips_pool_without_database_url(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        assert app.state.db is None
