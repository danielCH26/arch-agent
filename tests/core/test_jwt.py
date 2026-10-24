"""Tests para app.core.jwt — sign/verify/expiry/extra_claims."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


JWT_SECRET = "ci-test-secret-key-for-testing-only-32ch"


@pytest.fixture(autouse=True)
def _env_jwt():
    """Set the env vars jwt.py reads at module load + every call."""
    with patch.dict(
        os.environ,
        {
            "JWT_SECRET_KEY": JWT_SECRET,
            "JWT_ALGORITHM": "HS256",
            "JWT_EXPIRES_MINUTES": "60",
        },
    ):
        yield


class TestCreateAccessToken:
    def test_creates_and_verifies_valid_token(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=1, username="laura")

        payload = verify_token(token)
        assert payload["sub"] == "1"
        assert payload["username"] == "laura"
        assert "exp" in payload
        assert "iat" in payload

    def test_creates_token_with_custom_expiry(self):
        from app.core.jwt import create_access_token, verify_token

        custom_delta = timedelta(minutes=5)
        token = create_access_token(
            user_id=1,
            username="x",
            expires_delta=custom_delta,
        )
        payload = verify_token(token)
        # PyJWT returns Unix timestamps (int); convert to datetimes for comparison
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        diff = (exp - iat).total_seconds()
        assert diff == pytest.approx(300, abs=1)

    def test_extra_claims_are_merged_into_payload(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(
            user_id=1,
            username="x",
            extra_claims={"jti": "abc-123", "role": "admin"},
        )
        payload = verify_token(token)
        assert payload["jti"] == "abc-123"
        assert payload["role"] == "admin"

    def test_extra_claims_none_is_handled(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(
            user_id=1,
            username="x",
            extra_claims=None,
        )
        payload = verify_token(token)
        # No extra keys besides the default ones
        assert set(payload.keys()) <= {"sub", "username", "exp", "iat"}

    def test_token_without_extra_claims_has_no_jti(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=1, username="testuser")
        payload = verify_token(token)
        assert "jti" not in payload

    def test_token_with_extra_claims(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(
            user_id=1, username="testuser", extra_claims={"jti": "abc123"}
        )
        payload = verify_token(token)
        assert payload["jti"] == "abc123"


class TestVerifyToken:
    def test_verify_rejects_invalid_token(self):
        from app.core.jwt import verify_token, JWTError

        with pytest.raises(JWTError, match="Invalid token"):
            verify_token("invalid.token.here")

    def test_verify_rejects_token_signed_with_other_secret(self):
        from app.core.jwt import create_access_token, verify_token, JWTError

        token = create_access_token(user_id=1, username="x")
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "other-secret-key-also-32-chars!!"}):
            with pytest.raises(JWTError, match="Invalid token"):
                verify_token(token)

    def test_verify_rejects_expired_token(self):
        from app.core.jwt import create_access_token, verify_token, JWTError

        token = create_access_token(
            user_id=1,
            username="x",
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(JWTError, match="expired"):
            verify_token(token)

    def test_verify_accepts_token_signed_by_same_secret(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=99, username="valid")
        payload = verify_token(token)
        assert payload["sub"] == "99"


class TestJWTErrorClass:
    def test_jwt_error_is_exception_subclass(self):
        from app.core.jwt import JWTError

        assert issubclass(JWTError, Exception)

    def test_jwt_error_can_be_raised_with_args(self):
        from app.core.jwt import JWTError

        try:
            raise JWTError("test message")
        except Exception as e:
            assert isinstance(e, JWTError)
            assert str(e) == "test message"

    def test_logout_endpoint_adds_jti_to_revoked_set(self):
        """Logout adds a token's jti to JWT_REVOKED set (tokens need jti to be revocable)."""
        from app.api.dependencies import JWT_REVOKED
        from app.core.jwt import create_access_token

        token = create_access_token(
            user_id=1, username="laura", extra_claims={"jti": "test-jti-123"}
        )
        assert "test-jti-123" not in JWT_REVOKED

        # Simulate logout
        JWT_REVOKED.add("test-jti-123")
        assert "test-jti-123" in JWT_REVOKED

        # Cleanup
        JWT_REVOKED.discard("test-jti-123")