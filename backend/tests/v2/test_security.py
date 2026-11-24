"""Tests for bearer extraction, opaque session tokens, and password hashing.

No network and no database: these are the local cryptographic primitives that
``services.auth`` builds on.
"""
from __future__ import annotations

import hashlib
import re

import pytest

from backend.app.core.security import (
    AuthError,
    dummy_verify_password,
    extract_bearer_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


def test_generate_session_token_is_random_urlsafe_and_long_enough():
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert len(first) >= 32
    assert _TOKEN_RE.match(first)


def test_hash_session_token_is_a_stable_sha256_hex_digest():
    token = "opaque-session-token"
    digest = hash_session_token(token)

    assert digest == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert digest == hash_session_token(token)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert hash_session_token(token + "x") != digest


def test_hash_password_produces_salted_argon2id_hashes():
    password = "correct horse battery staple"
    first = hash_password(password)
    second = hash_password(password)

    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    # A per-hash salt means the same password never produces the same hash.
    assert first != second


def test_verify_password_accepts_only_the_matching_password():
    stored = hash_password("s3cret-password")

    assert verify_password(stored, "s3cret-password") is True
    assert verify_password(stored, "s3cret-passworD") is False
    assert verify_password(stored, "") is False


def test_verify_password_treats_a_corrupt_hash_as_a_mismatch():
    assert verify_password("not-an-argon2-hash", "anything") is False


def test_dummy_verification_always_fails():
    assert dummy_verify_password("whatever") is False
