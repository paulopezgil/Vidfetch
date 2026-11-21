"""Tests for application assembly, SPA serving, CORS, and lifespan behavior."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigError
from backend.app import main as main_module
from backend.app.main import create_app
from backend.tests.v2.fakes import app_client, make_settings


def test_root_returns_json_when_frontend_absent(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["app"] == "vidfetch"


def test_spa_is_served_without_shadowing_api(tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-index</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('hi')", encoding="utf-8")
    settings = make_settings(tmp_path, FRONTEND_DIST=dist)

    with app_client(settings) as (app, client):
        root = client.get("/")
        deep_link = client.get("/admin/users")
        asset = client.get("/assets/app.js")
        api = client.get("/api/health")
        unknown_api = client.get("/api/nope")

    assert root.status_code == 200
    assert root.text == "<html>spa-index</html>"
    assert deep_link.status_code == 200
    assert deep_link.text == "<html>spa-index</html>"
    assert asset.status_code == 200
    assert "console.log" in asset.text
    assert api.status_code == 200
    assert api.json()["status"] == "degraded"
    assert unknown_api.status_code == 404
    assert unknown_api.json()["error"]["code"] == "not_found"
    assert unknown_api.text != "<html>spa-index</html>"


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
        assert created and created[0].database_url.startswith("postgresql://")

    assert pool.closed is True
    assert app.state.db is None


def test_lifespan_skips_pool_without_database_url(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        assert app.state.db is None
