"""Tests para /api/users/* — get/update profile y change password."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def _client(user: dict | None = None):
    """Yield TestClient with auth override on server.app."""
    from fastapi.testclient import TestClient
    from server import app
    from app.api.dependencies import get_current_user

    if user is None:
        user = {"user_id": 1, "username": "laura", "jti": None}
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


class TestGetProfileEndpoint:
    """Integration tests for GET /api/users/me."""

    def test_returns_profile(self):
        profile = {
            "id": 7,
            "username": "laura",
            "email": "laura@test.com",
            "created_at": "2026-08-01T00:00:00",
        }

        with _client() as client, patch("app.api.users.get_profile", return_value=profile):
            resp = client.get("/api/users/me")

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 7
        assert body["username"] == "laura"
        assert body["email"] == "laura@test.com"
        assert body["created_at"] == "2026-08-01T00:00:00"

    def test_returns_profile_without_created_at(self):
        profile = {
            "id": 7,
            "username": "laura",
            "email": "laura@test.com",
        }

        with _client() as client, patch("app.api.users.get_profile", return_value=profile):
            resp = client.get("/api/users/me")

        assert resp.status_code == 200
        assert resp.json()["created_at"] is None

    def test_validation_error_maps_to_404(self):
        from app.auth.validators import ValidationError

        with (
            _client() as client,
            patch("app.api.users.get_profile", side_effect=ValidationError("User not found")),
        ):
            resp = client.get("/api/users/me")

        assert resp.status_code == 404
        assert "User not found" in resp.json()["detail"]


class TestUpdateProfileEndpoint:
    """Integration tests for PATCH /api/users/me."""

    def test_updates_username_and_email(self):
        profile = {
            "id": 7,
            "username": "newname",
            "email": "new@test.com",
            "created_at": "2026-08-01T00:00:00",
        }

        with (
            _client() as client,
            patch("app.api.users.update_profile") as mock_update,
            patch("app.api.users.get_profile", return_value=profile),
        ):
            resp = client.patch(
                "/api/users/me",
                json={"username": "newname", "email": "new@test.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["username"] == "newname"
        assert resp.json()["email"] == "new@test.com"
        mock_update.assert_called_once_with(
            1, email="new@test.com", username="newname"
        )

    def test_updates_only_username(self):
        profile = {
            "id": 7,
            "username": "newname",
            "email": "same@test.com",
        }

        with (
            _client() as client,
            patch("app.api.users.update_profile") as mock_update,
            patch("app.api.users.get_profile", return_value=profile),
        ):
            resp = client.patch("/api/users/me", json={"username": "newname"})

        assert resp.status_code == 200
        mock_update.assert_called_once_with(1, email=None, username="newname")

    def test_updates_only_email(self):
        profile = {
            "id": 7,
            "username": "same",
            "email": "new@test.com",
        }

        with (
            _client() as client,
            patch("app.api.users.update_profile") as mock_update,
            patch("app.api.users.get_profile", return_value=profile),
        ):
            resp = client.patch("/api/users/me", json={"email": "new@test.com"})

        assert resp.status_code == 200
        mock_update.assert_called_once_with(1, email="new@test.com", username=None)

    def test_validation_error_maps_to_409(self):
        from app.auth.validators import ValidationError

        with (
            _client() as client,
            patch(
                "app.api.users.update_profile",
                side_effect=ValidationError("Username already taken"),
            ),
        ):
            resp = client.patch(
                "/api/users/me", json={"username": "taken", "email": "x@y.com"}
            )

        assert resp.status_code == 409
        assert "Username already taken" in resp.json()["detail"]


class TestChangePasswordEndpoint:
    """Integration tests for PUT /api/users/me/password."""

    def test_changes_password_returns_204(self):
        with _client() as client, patch("app.api.users.change_password") as mock_change:
            resp = client.put(
                "/api/users/me/password",
                json={"current_password": "Old@1234", "new_password": "New@5678"},
            )

        assert resp.status_code == 204
        mock_change.assert_called_once_with(
            1, current_password="Old@1234", new_password="New@5678"
        )

    def test_wrong_current_password_returns_409(self):
        from app.auth.validators import ValidationError

        with (
            _client() as client,
            patch(
                "app.api.users.change_password",
                side_effect=ValidationError("Current password is incorrect"),
            ),
        ):
            resp = client.put(
                "/api/users/me/password",
                json={"current_password": "wrong", "new_password": "New@5678"},
            )

        assert resp.status_code == 409
        assert "incorrect" in resp.json()["detail"]

    def test_weak_new_password_returns_409(self):
        from app.auth.validators import ValidationError

        with (
            _client() as client,
            patch(
                "app.api.users.change_password",
                side_effect=ValidationError("New password does not meet complexity rules"),
            ),
        ):
            resp = client.put(
                "/api/users/me/password",
                json={"current_password": "Old@1234", "new_password": "weak"},
            )

        assert resp.status_code == 409


class TestUserOutModels:
    """Tests de Pydantic models de users."""

    def test_user_out_with_all_fields(self):
        from app.api.users import UserOut

        u = UserOut(id=1, username="laura", email="laura@test.com", created_at="2026-01-01")
        assert u.id == 1
        assert u.email == "laura@test.com"

    def test_user_out_optional_created_at(self):
        from app.api.users import UserOut

        u = UserOut(id=1, username="x", email="x@y.com")
        assert u.created_at is None

    def test_update_profile_request_partial(self):
        from app.api.users import UpdateProfileRequest

        u = UpdateProfileRequest(username="new")
        assert u.username == "new"
        assert u.email is None

    def test_change_password_request(self):
        from app.api.users import ChangePasswordRequest

        r = ChangePasswordRequest(current_password="Old@1234", new_password="New@5678")
        assert r.current_password == "Old@1234"
        assert r.new_password == "New@5678"