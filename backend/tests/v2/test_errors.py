"""Tests for the consistent API error envelope and exception handlers."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core.config import ConfigError
from backend.app.core.security import AuthError
from backend.app.api.errors import ServiceUnavailableError
from backend.app.main import create_app
from backend.app.services.signing import MediaTokenError
from backend.tests.v2.fakes import make_settings


def _build_app(tmp_path) -> FastAPI:
    app = create_app(make_settings(tmp_path))

    @app.get("/raise-auth")
    async def raise_auth(code: str = "missing_token") -> dict:
        raise AuthError(code, "Authentication failed.")

    @app.get("/raise-media")
    async def raise_media() -> dict:
        raise MediaTokenError("invalid_token", "Invalid media token.")

    @app.get("/raise-config")
    async def raise_config() -> dict:
        raise ConfigError("Missing DATABASE_URL and service-role-secret")

    @app.get("/raise-service")
    async def raise_service() -> dict:
        raise ServiceUnavailableError("Database is down.")

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("super-secret-token-value")

    @app.get("/needs-int")
    async def needs_int(value: int) -> dict:
        return {"value": value}

    return app


def test_auth_error_defaults_to_401(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/raise-auth")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "missing_token",
            "message": "Authentication failed.",
        }
    }


def test_auth_error_approval_and_admin_are_403(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        approval = client.get("/raise-auth?code=approval_required")
        admin = client.get("/raise-auth?code=admin_required")

    assert approval.status_code == 403
    assert approval.json()["error"]["code"] == "approval_required"
    assert admin.status_code == 403
    assert admin.json()["error"]["code"] == "admin_required"


def test_auth_error_service_unavailable_is_503(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/raise-auth?code=service_unavailable")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_media_token_error_is_401(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/raise-media")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_config_error_is_503_without_leaking_variable_names(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/raise-config")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "DATABASE_URL" not in response.text
    assert "service-role-secret" not in response.text


def test_service_unavailable_error_is_503(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/raise-service")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_unhandled_error_is_safe_500(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "super-secret-token-value" not in response.text


def test_unknown_route_uses_error_envelope(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_error_is_400(tmp_path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/needs-int?value=not-a-number")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
