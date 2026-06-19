"""Unit tests for core security primitives: Argon2 password hashing, JWT
token round-trips, and Fernet encrypt/decrypt. No DB or Redis required.
"""
from datetime import timedelta

import pytest
from jose import jwt

from src.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    encrypt,
    decrypt,
)
from src.core.config import get_settings


# ── Password hashing ────────────────────────────────────────────────────────


def test_hash_password_is_not_plaintext():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert h.startswith("$argon2")


def test_verify_password_roundtrip():
    h = hash_password("CorrectHorse1")
    assert verify_password("CorrectHorse1", h) is True


def test_verify_password_wrong():
    h = hash_password("CorrectHorse1")
    assert verify_password("wrong", h) is False


def test_verify_password_invalid_hash_returns_false():
    # Malformed hash must not raise — returns False.
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_password_salts_differ():
    assert hash_password("same") != hash_password("same")


# ── JWT tokens ──────────────────────────────────────────────────────────────


def test_access_token_roundtrip():
    token = create_access_token("user-123", org_id="org-9")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["org"] == "org-9"
    assert payload["type"] == "access"


def test_access_token_with_scope():
    token = create_access_token("u", org_id=None, scope="device")
    payload = decode_token(token)
    assert payload["scope"] == "device"


def test_refresh_token_carries_version_and_jti():
    token = create_refresh_token("user-7", token_version=5)
    payload = decode_token(token)
    assert payload["type"] == "refresh"
    assert payload["tv"] == 5
    assert "jti" in payload


def test_decode_rejects_tampered_token():
    token = create_access_token("u")
    with pytest.raises(Exception):
        decode_token(token + "tamper")


def test_decode_rejects_wrong_secret():
    token = jwt.encode({"sub": "x", "type": "access"}, "a-different-secret", algorithm=get_settings().algorithm)
    with pytest.raises(Exception):
        decode_token(token)


# ── Fernet encryption ───────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    secret = "sk-provider-credential-value"
    assert decrypt(encrypt(secret)) == secret


def test_encrypt_is_nondeterministic():
    # Fernet embeds a random IV → ciphertext differs each call.
    assert encrypt("same") != encrypt("same")


def test_encrypt_handles_unicode():
    s = "clé-secrète-日本語"
    assert decrypt(encrypt(s)) == s
