"""
Unit tests for app.core.attachment_tokens (F13, REQ-ATT-2).

Covers:
- sign_attachment_token / verify_attachment_token round-trip
- Expired token detection
- Bad signature detection
- Mismatched attachment_id detection
- Mismatched user_id detection
- Empty token handling
- Non-dict payload handling
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_serializer(monkeypatch):
    """Reset the serializer before each test so env var changes are honored."""
    from app.core import attachment_tokens

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-attachments")
    attachment_tokens.reset_serializer_for_tests()
    yield
    attachment_tokens.reset_serializer_for_tests()


def test_verify_returns_valid_and_uid_on_good_token():
    """Happy path: valid token returns (True, user_id)."""
    from app.core import attachment_tokens

    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    valid, payload_uid = attachment_tokens.verify_attachment_token(
        token,
        attachment_id="att-123",
        user_id=42,
    )
    assert valid is True
    assert payload_uid == 42


def test_verify_returns_false_none_on_expired():
    """Expired token returns (False, None)."""
    import time
    from app.core import attachment_tokens

    # Sign with a very short TTL
    token = attachment_tokens.sign_attachment_token("att-123", user_id=42, ttl=1)
    # Wait for it to expire
    time.sleep(1.5)
    valid, payload_uid = attachment_tokens.verify_attachment_token(
        token,
        attachment_id="att-123",
        user_id=42,
        max_age=1,
    )
    assert valid is False
    assert payload_uid is None


def test_verify_returns_false_none_on_bad_signature():
    """Mangled token returns (False, None)."""
    from app.core import attachment_tokens

    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    # Mangle the token by appending a character
    mangled = token + "x"
    valid, payload_uid = attachment_tokens.verify_attachment_token(
        mangled,
        attachment_id="att-123",
        user_id=42,
    )
    assert valid is False
    assert payload_uid is None


def test_verify_returns_false_none_on_mismatched_aid():
    """Token signed for attachment A, verified for attachment B returns (False, None)."""
    from app.core import attachment_tokens

    token = attachment_tokens.sign_attachment_token("att-A", user_id=42)
    valid, payload_uid = attachment_tokens.verify_attachment_token(
        token,
        attachment_id="att-B",  # Different from what was signed
        user_id=42,
    )
    assert valid is False
    assert payload_uid is None


def test_verify_returns_false_none_on_mismatched_uid():
    """Token signed for user 42, verified for user 99 returns (False, None)."""
    from app.core import attachment_tokens

    token = attachment_tokens.sign_attachment_token("att-123", user_id=42)
    valid, payload_uid = attachment_tokens.verify_attachment_token(
        token,
        attachment_id="att-123",
        user_id=99,  # Different from what was signed
    )
    assert valid is False
    assert payload_uid is None


def test_verify_returns_false_none_on_empty_token():
    """Empty token returns (False, None)."""
    from app.core import attachment_tokens

    valid, payload_uid = attachment_tokens.verify_attachment_token(
        "",
        attachment_id="att-123",
        user_id=42,
    )
    assert valid is False
    assert payload_uid is None


def test_verify_returns_false_none_on_non_dict_payload():
    """Non-dict payload (e.g., a list) returns (False, None)."""
    from app.core import attachment_tokens
    from unittest.mock import patch

    # Create a serializer that returns a non-dict payload
    with patch.object(attachment_tokens, "_get_serializer") as mock_serializer:
        mock_ser = pytest.importorskip("itsdangerous").URLSafeTimedSerializer(
            attachment_tokens._derive_key(), salt=attachment_tokens._SALT
        )
        mock_serializer.return_value = mock_ser

        # Manually create a token with a list payload (not a dict)
        # by patching the loads to return a list
        original_loads = mock_ser.loads

        def mock_loads(token, max_age):
            # Return a list instead of a dict
            return ["not", "a", "dict"]

        with patch.object(mock_ser, "loads", side_effect=mock_loads):
            valid, payload_uid = attachment_tokens.verify_attachment_token(
                "fake-token",
                attachment_id="att-123",
                user_id=42,
            )
            assert valid is False
            assert payload_uid is None
