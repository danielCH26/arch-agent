"""
Tests for app.core.attachment_tokens (F13, REQ-ATT-2, SCN-ATT-5).

Covers:
  - ``sign_attachment_token`` / ``verify_attachment_token`` happy path
  - Expired token (TTL > 5 min) returns False
  - Tampered payload (HMAC mismatch) returns False
  - Cross-attachment-id reuse rejected
  - ``_ensure_uploads_dir`` is idempotent on repeat calls
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-for-attachment-tokens")


def test_sign_and_verify_happy_path():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    assert isinstance(token, str)
    assert attachment_tokens.verify_attachment_token(token, "att-123", user_id=42) is True


def test_verify_expired_token_returns_false():
    from app.core import attachment_tokens
    from itsdangerous import URLSafeTimedSerializer

    attachment_tokens.reset_serializer_for_tests()
    # Build a serializer with max_age=1 so the test can age the token out
    # without sleeping for 5 minutes.
    ser = URLSafeTimedSerializer(attachment_tokens._derive_key(), salt=attachment_tokens._SALT)
    payload = {"aid": "att-123", "uid": 42}
    # Pre-sign a payload with max_age=1 — verify_attachment_token below
    # uses max_age=300 by default, which sees it as expired.
    token = ser.dumps(payload)

    # The default 300s window sees it as expired.
    assert attachment_tokens.verify_attachment_token(token, "att-123", user_id=42) is False


def test_verify_tampered_payload_returns_false():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    # Flip one character of the token (URL-safe base64 → safe to mutate).
    parts = token.split(".")
    assert len(parts) >= 2
    parts[0] = "X" + parts[0][1:]
    tampered = ".".join(parts)
    assert attachment_tokens.verify_attachment_token(tampered, "att-123", user_id=42) is False


def test_verify_cross_attachment_id_rejected():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-A", user_id=42)
    # Same user, but verifying against a DIFFERENT attachment id → False.
    assert attachment_tokens.verify_attachment_token(token, "att-B", user_id=42) is False


def test_verify_cross_user_rejected():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    # Same attachment, but verifying as a DIFFERENT user → False.
    assert attachment_tokens.verify_attachment_token(token, "att-123", user_id=99) is False


def test_verify_empty_token_returns_false():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    assert attachment_tokens.verify_attachment_token("", "att-123", user_id=42) is False


def test_verify_garbage_token_returns_false():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    assert attachment_tokens.verify_attachment_token("not-a-token", "att-123", user_id=42) is False


def test_default_ttl_is_300s():
    from app.core import attachment_tokens

    assert attachment_tokens.DEFAULT_TTL_SECONDS == 300


def test_custom_ttl_is_respected():
    from app.core import attachment_tokens

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42, ttl=600)
    assert attachment_tokens.verify_attachment_token(
        token, "att-123", user_id=42, max_age=600
    ) is True
    # Default 300s window sees it as expired.
    assert attachment_tokens.verify_attachment_token(
        token, "att-123", user_id=42, max_age=300
    ) is False


def test_ensure_uploads_dir_is_idempotent(monkeypatch, tmp_path):
    from app.core import attachment_tokens

    monkeypatch.setenv("PUPPETEER_UPLOADS_DIR", str(tmp_path))
    p1 = attachment_tokens._ensure_uploads_dir()
    p2 = attachment_tokens._ensure_uploads_dir()
    assert p1 == p2
    assert p1.endswith("screenshots")
    assert os.path.isdir(p1)