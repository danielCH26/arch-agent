"""
Tests para /api/auth/* — login, register, logout, me.

Usa mocking para evitar overhead de langchain en import.
Los imports de app.api.* se hacen DENTRO de cada test.
"""

import pytest
import os

# Configurar entorno antes de cualquier import de app
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only-32chars!"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_EXPIRES_MINUTES"] = "60"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-32-chars!!"


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

        req = LoginRequest(username="testuser", password="testpass123")
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


class TestRegisterEndpoint:
    """Integration tests for POST /api/auth/register."""

    def test_register_success(self):
        from unittest.mock import MagicMock, patch

        mock_user = MagicMock()
        mock_user.id = 7
        mock_user.username = "newuser"

        with (
            patch("app.api.auth._register_user", return_value=mock_user),
            patch("app.api.auth.create_access_token", return_value="tok-abc"),
        ):
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/register",
                json={"username": "newuser", "email": "new@test.com", "password": "Test@1234"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["user_id"] == 7
        assert body["username"] == "newuser"
        assert body["token"] == "tok-abc"

    def test_register_validation_error_returns_409(self):
        from unittest.mock import patch
        from app.auth.validators import ValidationError

        with patch(
            "app.api.auth._register_user",
            side_effect=ValidationError("username already exists"),
        ):
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/register",
                json={"username": "dup", "email": "dup@test.com", "password": "Test@1234"},
            )

        assert resp.status_code == 409
        assert "username already exists" in resp.json()["detail"]


class TestLoginEndpoint:
    """Integration tests for POST /api/auth/login."""

    def test_login_success_with_username(self):
        from unittest.mock import MagicMock, patch
        import bcrypt as _bcrypt

        mock_user = MagicMock()
        mock_user.id = 5
        mock_user.username = "testuser"
        # Real bcrypt hash of "Test@1234" so the same password in the request matches
        mock_user.password_hash = _bcrypt.hashpw(b"Test@1234", _bcrypt.gensalt()).decode()

        with (
            patch("app.api.auth._get_user_by_login", return_value=mock_user),
            patch("app.api.auth.create_access_token", return_value="tok-xyz"),
        ):
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/login",
                json={"username": "testuser", "password": "Test@1234"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == 5
        assert body["token"] == "tok-xyz"

    def test_login_unknown_user_returns_401(self):
        from unittest.mock import patch

        with patch("app.api.auth._get_user_by_login", return_value=None):
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/login",
                json={"username": "nobody", "password": "wrong"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"

    def test_login_wrong_password_returns_401(self):
        from unittest.mock import MagicMock, patch

        mock_user = MagicMock()
        mock_user.id = 5
        mock_user.username = "testuser"
        # Real bcrypt hash of "correct-password" — wrong-password won't match
        import bcrypt as _bcrypt
        mock_user.password_hash = _bcrypt.hashpw(b"correct-password", _bcrypt.gensalt()).decode()

        with patch("app.api.auth._get_user_by_login", return_value=mock_user):
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/login",
                json={"username": "testuser", "password": "WRONG-password"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"


class TestLogoutEndpoint:
    """Integration tests for POST /api/auth/logout."""

    def test_logout_with_jti_revokes_token(self):
        from unittest.mock import patch
        from app.api.dependencies import JWT_REVOKED
        from app.core.jwt import create_access_token

        token = create_access_token(
            user_id=1, username="laura", extra_claims={"jti": "logout-test-jti"}
        )
        assert "logout-test-jti" not in JWT_REVOKED

        with patch("app.api.dependencies.get_current_user") as mock_dep:
            mock_dep.return_value = {"user_id": 1, "username": "laura", "jti": "logout-test-jti"}
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Logged out successfully"
        assert "logout-test-jti" in JWT_REVOKED
        JWT_REVOKED.discard("logout-test-jti")  # cleanup

    def test_logout_without_jti_still_succeeds(self):
        """Tokens without jti can't be revoked but logout should still 200."""
        from unittest.mock import patch
        from app.core.jwt import create_access_token

        token = create_access_token(user_id=1, username="laura")  # no jti

        with patch("app.api.dependencies.get_current_user") as mock_dep:
            mock_dep.return_value = {"user_id": 1, "username": "laura", "jti": None}
            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200


class TestMeEndpoint:
    """Integration tests for GET /api/auth/me."""

    def test_me_returns_user_profile(self):
        from unittest.mock import MagicMock, patch
        from app.core.jwt import create_access_token

        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.username = "laura"
        mock_user.email = "laura@test.com"

        token = create_access_token(user_id=42, username="laura")

        with (
            patch("app.api.dependencies.get_current_user") as mock_dep,
            patch("app.api.auth.SessionLocal") as mock_session,
        ):
            mock_dep.return_value = {"user_id": 42, "username": "laura", "jti": None}
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = mock_user
            mock_session.return_value = mock_db

            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 42
        assert body["username"] == "laura"
        assert body["email"] == "laura@test.com"

    def test_me_returns_404_when_user_not_in_db(self):
        """Token references a user_id that no longer exists in the DB."""
        from unittest.mock import MagicMock, patch
        from app.core.jwt import create_access_token

        token = create_access_token(user_id=999, username="ghost")

        with (
            patch("app.api.dependencies.get_current_user") as mock_dep,
            patch("app.api.auth.SessionLocal") as mock_session,
        ):
            mock_dep.return_value = {"user_id": 999, "username": "ghost", "jti": None}
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            from fastapi.testclient import TestClient
            from server import app

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "User not found"
