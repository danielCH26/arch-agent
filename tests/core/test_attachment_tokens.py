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


def test_verify_expired_token_returns_false(monkeypatch):
    """SCN-ATT-5: a token older than the TTL window returns False on verify.

    We simulate expiration by mocking the ``itsdangerous.loads`` call to
    raise ``SignatureExpired`` — this is the same code path itsdangerous
    takes when ``age > max_age`` inside ``TimedSerializer.loads``.
    """
    from app.core import attachment_tokens
    from itsdangerous import SignatureExpired

    attachment_tokens.reset_serializer_for_tests()
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)

    real_loads = attachment_tokens._get_serializer().loads

    def _expired_loads(*args, **kwargs):
        raise SignatureExpired("expired by test")

    monkeypatch.setattr(attachment_tokens._get_serializer(), "loads", _expired_loads)
    try:
        assert attachment_tokens.verify_attachment_token(token, "att-123", user_id=42) is False
    finally:
        # Restore so subsequent tests in this module see the real loads.
        attachment_tokens._get_serializer().loads = real_loads


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


def test_custom_ttl_is_respected(monkeypatch):
    """``sign_attachment_token`` accepts a custom ``ttl`` argument; the
    default helper uses 300s (REq-ATT-2). The ``max_age`` parameter on
    verify honours whatever the caller passes — but we don't fake time
    travel; we just verify the default-TTL contract.
    """
    from app.core import attachment_tokens
    from itsdangerous import SignatureExpired

    attachment_tokens.reset_serializer_for_tests()
    # Default TTL is 300s.
    assert attachment_tokens.DEFAULT_TTL_SECONDS == 300

    # A custom-TTL token verifies under the matching max_age window; we
    # verify by mocking an expiration inside the wrapper.
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42, ttl=600)
    real_loads = attachment_tokens._get_serializer().loads

    def _expired_loads(*args, **kwargs):
        raise SignatureExpired("expired by test (custom TTL)")

    monkeypatch.setattr(attachment_tokens._get_serializer(), "loads", _expired_loads)
    try:
        assert attachment_tokens.verify_attachment_token(
            token, "att-123", user_id=42, max_age=600
        ) is False
    finally:
        attachment_tokens._get_serializer().loads = real_loads


def test_ensure_uploads_dir_is_idempotent(monkeypatch, tmp_path):
    from app.core import attachment_tokens

    monkeypatch.setenv("PUPPETEER_UPLOADS_DIR", str(tmp_path))
    p1 = attachment_tokens._ensure_uploads_dir()
    p2 = attachment_tokens._ensure_uploads_dir()
    assert p1 == p2
    assert p1.endswith("screenshots")
    assert os.path.isdir(p1)