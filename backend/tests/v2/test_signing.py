"""Tests for HMAC-signed media tokens."""
from __future__ import annotations

import re

import pytest

from backend.app.services.signing import (
    MediaTokenError,
    sign_media_token,
    verify_media_token,
)

SECRET = "media-token-secret"
ASSET = "6f1d7c2e-0000-4000-8000-000000000001"
USER = "11111111-1111-1111-1111-111111111111"


def test_roundtrip_returns_bound_claims():
    token = sign_media_token(SECRET, ASSET, USER, 300, now=1_000)

    verified = verify_media_token(token, SECRET, now=1_100)

    assert verified.asset_id == ASSET
    assert verified.user_id == USER
    assert verified.expires_at == 1_300


def test_token_is_url_safe():
    token = sign_media_token(SECRET, ASSET, USER, 300, now=1_000)

    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[0-9a-f]{64}", token)
    assert "=" not in token
    assert "/" not in token
    assert "+" not in token


def test_tampered_signature_is_rejected():
    token = sign_media_token(SECRET, ASSET, USER, 300, now=1_000)
    payload, signature = token.split(".")
    tampered = f"{payload}.{('0' if signature[0] != '0' else '1')}{signature[1:]}"

    with pytest.raises(MediaTokenError) as excinfo:
        verify_media_token(tampered, SECRET, now=1_100)

    assert excinfo.value.code == "invalid_token"


def test_tampered_payload_is_rejected():
    token = sign_media_token(SECRET, ASSET, USER, 300, now=1_000)
    payload, signature = token.split(".")
    tampered = f"{'A' if payload[0] != 'A' else 'B'}{payload[1:]}.{signature}"

    with pytest.raises(MediaTokenError) as excinfo:
        verify_media_token(tampered, SECRET, now=1_100)

    assert excinfo.value.code == "invalid_token"


def test_verification_with_wrong_secret_is_rejected():
    token = sign_media_token(SECRET, ASSET, USER, 300, now=1_000)

    with pytest.raises(MediaTokenError) as excinfo:
        verify_media_token(token, "another-secret", now=1_100)

    assert excinfo.value.code == "invalid_token"


def test_expiry_boundary_is_enforced():
    token = sign_media_token(SECRET, ASSET, USER, 60, now=1_000)

    # 1059 is still valid, 1060 (the expiry second) is not.
    assert verify_media_token(token, SECRET, now=1_059).expires_at == 1_060
    with pytest.raises(MediaTokenError) as excinfo:
        verify_media_token(token, SECRET, now=1_060)
    assert excinfo.value.code == "expired_token"


@pytest.mark.parametrize(
    "token",
    ["", "abc", "abc.def.ghi", ".abc", "abc.", "payload.nothex"],
)
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(MediaTokenError):
        verify_media_token(token, SECRET)


def test_sign_requires_secret_and_positive_ttl():
    with pytest.raises(ValueError):
        sign_media_token("", ASSET, USER, 60)
    with pytest.raises(ValueError):
        sign_media_token(SECRET, "", USER, 60)
    with pytest.raises(ValueError):
        sign_media_token(SECRET, ASSET, "", 60)
    with pytest.raises(ValueError):
        sign_media_token(SECRET, ASSET, USER, 0)
    with pytest.raises(ValueError):
        sign_media_token(SECRET, ASSET, USER, True)


def test_verify_requires_secret():
    token = sign_media_token(SECRET, ASSET, USER, 60, now=1_000)

    with pytest.raises(ValueError):
        verify_media_token(token, "")
