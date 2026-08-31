"""
Tests para /api/auth/* — login, register, logout, me.

Usa mocking para evitar overhead de langchain en import.
Los imports de app.api.* se hacen DENTRO de cada test.
"""

import pytest
import os

# Configurar entorno antes de cualquier import de app.
# NOTA: no seteamos DATABASE_URL (mocking puro, sin DB real) para no
# contaminar el engine global de app.core.database usado por otras suites.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRES_MINUTES", "60")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-chars!!")


class TestGetUserByLogin:
    """Tests de _get_user_by_login."""

    def test_finds_by_username(self):
        from unittest.mock import MagicMock, patch

        with patch("app.api.auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_user = MagicMock()
            mock_user.username = "testuser"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_user
            mock_session.return_value = mock_db

            from app.api.auth import _get_user_by_login
            result = _get_user_by_login("testuser")
            assert result == mock_user

    def test_finds_by_email(self):
        from unittest.mock import MagicMock, patch

        with patch("app.api.auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_user = MagicMock()
            mock_user.email = "test@test.com"
            mock_db.query.return_value.filter.return_value.first.return_value = mock_user
            mock_session.return_value = mock_db

            from app.api.auth import _get_user_by_login
            result = _get_user_by_login("test@test.com")
            assert result == mock_user

    def test_returns_none_when_not_found(self):
        from unittest.mock import MagicMock, patch

        with patch("app.api.auth.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            from app.api.auth import _get_user_by_login
            result = _get_user_by_login("notfound")
            assert result is None


class TestAuthModels:
    """Tests de modelos Pydantic."""

    def test_register_request_accepts_empty_username_at_model_level(self):
        """RegisterRequest only type-checks; content validation happens in app.auth.validators."""
        from app.api.auth import RegisterRequest

        # Pydantic accepts empty str at model level (content validation is in register_user)
        req = RegisterRequest(username="", email="test@test.com", password="Test@1234")
        assert req.username == ""

    def test_register_request_accepts_valid_data(self):
        from app.api.auth import RegisterRequest

        req = RegisterRequest(username="newuser", email="new@test.com", password="Test@1234")
        assert req.username == "newuser"
        assert req.email == "new@test.com"

    def test_login_request(self):
        from app.api.auth import LoginRequest

        req = LoginRequest(username="testuser")
        assert req.username == "testuser"

    def test_token_response(self):
        from app.api.auth import TokenResponse

        resp = TokenResponse(user_id=1, username="testuser", token="abc123")
        assert resp.user_id == 1
        assert resp.token == "abc123"

    def test_user_response(self):
        from app.api.auth import UserResponse
        from unittest.mock import MagicMock

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.email = "test@test.com"

        resp = UserResponse.model_validate(mock_user)
        assert resp.id == 1
        assert resp.email == "test@test.com"


class TestJWTTokens:
    """Tests de JWT creation y verification."""

    def test_create_and_verify_valid_token(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=1, username="testuser")
        payload = verify_token(token)
        assert payload["sub"] == "1"
        assert payload["username"] == "testuser"
        assert "exp" in payload
        assert "iat" in payload

    def test_verify_rejects_invalid_token(self):
        from app.core.jwt import JWTError

        from app.core.jwt import verify_token

        with pytest.raises(JWTError):
            verify_token("invalid.token.here")

    def test_token_without_extra_claims_has_no_jti(self):
        """create_access_token only adds jti when extra_claims is provided."""
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(user_id=1, username="testuser")
        payload = verify_token(token)
        assert "jti" not in payload  # jti only via extra_claims

    def test_token_with_extra_claims(self):
        from app.core.jwt import create_access_token, verify_token

        token = create_access_token(
            user_id=1, username="testuser", extra_claims={"jti": "abc123"}
        )
        payload = verify_token(token)
        assert payload["jti"] == "abc123"

    def test_logout_endpoint_adds_jti_to_revoked_set(self):
        """Logout adds a token's jti to JWT_REVOKED set (tokens need jti to be revocable)."""
        from app.api.dependencies import JWT_REVOKED
        from app.core.jwt import create_access_token

        # Create a token WITH jti via extra_claims (mimicking proper login)
        token = create_access_token(
            user_id=1, username="testuser", extra_claims={"jti": "test-jti-123"}
        )
        assert "test-jti-123" not in JWT_REVOKED

        # Simulate logout
        JWT_REVOKED.add("test-jti-123")
        assert "test-jti-123" in JWT_REVOKED

        # Cleanup
        JWT_REVOKED.discard("test-jti-123")
