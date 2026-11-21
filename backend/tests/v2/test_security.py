"""Tests for bearer extraction and Supabase JWT verification (HS256 path).

JWKS fetching is deliberately not exercised: these tests verify the local
cryptographic path with a real PyJWT signature, no network.
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientError

import backend.app.core.security as security_module
from backend.app.core.config import Settings
from backend.app.core.security import (
    AuthError,
    decode_supabase_token,
    extract_bearer_token,
)

ISSUER = "https://proj.supabase.co/auth/v1"
AUDIENCE = "authenticated"
SECRET = "test-shared-secret-0123456789"
SUBJECT = "11111111-1111-1111-1111-111111111111"


def _settings(**overrides: str) -> Settings:
    env = {
        "SUPABASE_URL": "https://proj.supabase.co",
        "SUPABASE_JWT_SECRET": SECRET,
        "DATABASE_URL": "postgresql://user:pass@pooler/db",
        "MEDIA_TOKEN_SECRET": "media-secret",
    }
    env.update(overrides)
    return Settings.from_env(env)


def _token(
    *,
    secret: str = SECRET,
    subject: str | None = SUBJECT,
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
    expires_in: int = 300,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    payload: dict = {
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
        "email": "user@example.test",
    }
    if subject is not None:
        payload["sub"] = subject
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def test_decode_valid_hs256_token():
    claims = decode_supabase_token(_token(), _settings())

    assert claims["sub"] == SUBJECT
    assert claims["aud"] == AUDIENCE
    assert claims["iss"] == ISSUER


def test_decode_rejects_expired_token():
    token = _token(expires_in=-10)

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings())

    assert excinfo.value.code == "token_expired"
    assert "expired" in excinfo.value.message.lower()


def test_decode_rejects_wrong_audience():
    token = _token(audience="some-other-app")

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings())

    assert excinfo.value.code == "invalid_audience"


def test_decode_rejects_wrong_issuer():
    token = _token(issuer="https://evil.example.test/auth/v1")

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings())

    assert excinfo.value.code == "invalid_issuer"


def test_decode_rejects_bad_signature():
    token = _token(secret="a-different-secret")

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings())

    assert excinfo.value.code == "invalid_token"


def test_decode_rejects_missing_subject():
    token = _token(subject=None)

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings())

    assert excinfo.value.code == "missing_subject"


def test_decode_rejects_malformed_token():
    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token("not-a-jwt", _settings())

    assert excinfo.value.code == "invalid_token"


def test_decode_requires_configured_auth():
    settings = Settings.from_env({"SUPABASE_URL": "", "SUPABASE_JWT_SECRET": ""})

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(_token(), settings)

    assert excinfo.value.code == "auth_not_configured"


def test_decode_does_not_trust_user_metadata_for_authorization():
    token = _token(
        extra={
            "user_metadata": {"is_approved": True, "app_role": "admin"},
            "app_metadata": {"app_role": "admin"},
        }
    )

    claims = decode_supabase_token(token, _settings())

    # The verifier returns verified claims only; it must not synthesize
    # approval or application roles from metadata. Those come from profiles.
    assert "is_approved" not in claims
    assert "app_role" not in claims
    assert claims["user_metadata"] == {
        "is_approved": True,
        "app_role": "admin",
    }


@pytest.mark.parametrize(
    "header",
    ["Bearer abc.def.ghi", "bearer abc.def.ghi", "  Bearer   token-value  "],
)
def test_extract_bearer_token_accepts_case_insensitive_scheme(header):
    assert extract_bearer_token(header) == header.strip().split(None, 1)[1].strip()


@pytest.mark.parametrize(
    "header",
    [None, "", "   ", "Bearer", "Basic abc", "Token abc", "Bearer a b"],
)
def test_extract_bearer_token_rejects_bad_headers(header):
    with pytest.raises(AuthError):
        extract_bearer_token(header)


def test_extract_bearer_token_distinguishes_missing_from_malformed():
    with pytest.raises(AuthError) as missing:
        extract_bearer_token(None)
    assert missing.value.code == "missing_token"

    with pytest.raises(AuthError) as malformed:
        extract_bearer_token("Basic abc")
    assert malformed.value.code == "invalid_authorization_header"


def test_jwks_path_verifies_rs256_and_caches_client(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    created: list = []

    class FakeSigningKey:
        def __init__(self, key) -> None:
            self.key = key

    class FakeJWKClient:
        def __init__(self, url: str, cache_keys: bool = True) -> None:
            self.url = url
            self.cache_keys = cache_keys
            self.calls = 0
            created.append(self)

        def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
            self.calls += 1
            return FakeSigningKey(public_key)

    monkeypatch.setattr(security_module, "PyJWKClient", FakeJWKClient)
    monkeypatch.setattr(security_module, "_JWKS_CLIENTS", {})

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": SUBJECT,
            "aud": AUDIENCE,
            "iss": ISSUER,
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
    )
    settings = _settings(SUPABASE_JWT_SECRET="")

    first = decode_supabase_token(token, settings)
    second = decode_supabase_token(token, settings)

    assert first["sub"] == second["sub"] == SUBJECT
    assert len(created) == 1
    assert created[0].url == settings.supabase_jwks_url
    assert created[0].calls == 2


def test_jwks_fetch_failure_maps_to_safe_error(monkeypatch):
    class FailingJWKClient:
        def __init__(self, url: str, cache_keys: bool = True) -> None:
            self.url = url

        def get_signing_key_from_jwt(self, token: str):
            raise PyJWKClientError("network down")

    monkeypatch.setattr(security_module, "PyJWKClient", FailingJWKClient)
    monkeypatch.setattr(security_module, "_JWKS_CLIENTS", {})

    token = jwt.encode(
        {"sub": SUBJECT, "aud": AUDIENCE, "iss": ISSUER,
         "exp": int(time.time()) + 300},
        "irrelevant",
        algorithm="HS256",
    )

    with pytest.raises(AuthError) as excinfo:
        decode_supabase_token(token, _settings(SUPABASE_JWT_SECRET=""))

    assert excinfo.value.code == "jwks_unavailable"
    assert "network down" not in excinfo.value.message
