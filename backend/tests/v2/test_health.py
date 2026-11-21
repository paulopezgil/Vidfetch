"""Tests for the public health endpoint."""
from __future__ import annotations

from backend.tests.v2.fakes import FakeDatabase, app_client, make_settings
from backend.version import APP_VERSION


def test_health_is_public_and_degraded_without_database(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] is False
    assert body["auth"] is True
    assert body["version"] == APP_VERSION
    assert isinstance(body["yt_dlp_version"], str)
    assert body["storage"]["writable"] is True
    assert body["storage"]["free_bytes"] >= 0
    assert set(body["dependencies"]) == {"ffmpeg", "node"}
    # No secrets leak into the public payload.
    assert "test-jwt-secret" not in response.text


def test_health_reports_ok_when_database_is_reachable(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase()
    db.queue_fetchrow({"ok": 1})

    with app_client(settings, db) as (app, client):
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True


def test_health_reports_degraded_when_database_query_fails(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase(fail_with=ConnectionError("pool is down"))

    with app_client(settings, db) as (app, client):
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] is False
