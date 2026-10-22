"""Tests for app/api/users.py.

Covers the /api/users/me endpoints (read profile, update profile, change password).
Uses pure mocking (no DB) per tests/api/conftest.py convention.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api.users import (
    ChangePasswordRequest,
    UpdateProfileRequest,
    UserOut,
    change_current_user_password,
    get_current_user_profile,
    update_current_user_profile,
)
from app.auth.validators import ValidationError


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TestUserOut:
    def test_round_trip(self):
        out = UserOut(id=1, username="alice", email="alice@test.com", created_at="2025-01-01T00:00:00")
        assert out.id == 1
        assert out.username == "alice"
        assert out.email == "alice@test.com"
        assert out.created_at == "2025-01-01T00:00:00"

    def test_created_at_is_optional(self):
        out = UserOut(id=2, username="bob", email="bob@test.com")
        assert out.created_at is None


class TestUpdateProfileRequest:
    def test_all_fields_optional(self):
        body = UpdateProfileRequest()
        assert body.username is None
        assert body.email is None

    def test_username_only(self):
        body = UpdateProfileRequest(username="alice2")
        assert body.username == "alice2"
        assert body.email is None

    def test_email_only(self):
        body = UpdateProfileRequest(email="alice2@test.com")
        assert body.username is None
        assert body.email == "alice2@test.com"


class TestChangePasswordRequest:
    def test_requires_both_passwords(self):
        body = ChangePasswordRequest(current_password="old", new_password="new")
        assert body.current_password == "old"
        assert body.new_password == "new"


# ---------------------------------------------------------------------------
# GET /api/users/me
# ---------------------------------------------------------------------------

class TestGetCurrentUserProfile(unittest.IsolatedAsyncioTestCase):
    async def test_returns_profile(self):
        profile_data = {
            "id": 1,
            "username": "alice",
            "email": "alice@test.com",
            "created_at": "2025-01-01T00:00:00",
        }
        current_user = {"user_id": 1, "username": "alice"}

        with patch("app.api.users.get_profile", return_value=profile_data) as mock_get:
            result = await get_current_user_profile(current_user=current_user)

        assert isinstance(result, UserOut)
        assert result.id == 1
        assert result.username == "alice"
        assert result.email == "alice@test.com"
        assert result.created_at == "2025-01-01T00:00:00"
        mock_get.assert_called_once_with(1)

    async def test_returns_404_on_validation_error(self):
        current_user = {"user_id": 999, "username": "ghost"}

        with patch("app.api.users.get_profile", side_effect=ValidationError("User not found")):
            with self.assertRaises(Exception) as exc_info:
                await get_current_user_profile(current_user=current_user)

        assert getattr(exc_info.exception, "status_code", None) == 404
        assert "User not found" in str(exc_info.exception.detail)

    async def test_uses_user_id_from_token(self):
        """The endpoint must read user_id from the token, not from query/body."""
        profile_data = {"id": 42, "username": "x", "email": "x@x.com", "created_at": None}

        with patch("app.api.users.get_profile", return_value=profile_data) as mock_get:
            await get_current_user_profile(current_user={"user_id": 42, "username": "x"})

        mock_get.assert_called_once_with(42)


# ---------------------------------------------------------------------------
# PATCH /api/users/me
# ---------------------------------------------------------------------------

class TestUpdateCurrentUserProfile(unittest.IsolatedAsyncioTestCase):
    async def test_updates_and_returns_new_profile(self):
        profile_after = {"id": 1, "username": "alice2", "email": "alice2@test.com", "created_at": None}

        current_user = {"user_id": 1, "username": "alice"}
        body = UpdateProfileRequest(username="alice2", email="alice2@test.com")

        with patch("app.api.users.update_profile") as mock_update, \
             patch("app.api.users.get_profile", return_value=profile_after):
            result = await update_current_user_profile(body=body, current_user=current_user)

        assert isinstance(result, UserOut)
        assert result.username == "alice2"
        assert result.email == "alice2@test.com"
        # update_profile called with both fields
        mock_update.assert_called_once_with(
            1,
            email="alice2@test.com",
            username="alice2",
        )

    async def test_supports_username_only_update(self):
        body = UpdateProfileRequest(username="only_username")
        with patch("app.api.users.update_profile") as mock_update, \
             patch("app.api.users.get_profile", return_value={"id": 1, "username": "x", "email": "x@x.com", "created_at": None}):
            await update_current_user_profile(body=body, current_user={"user_id": 1, "username": "x"})

        mock_update.assert_called_once_with(1, email=None, username="only_username")

    async def test_supports_email_only_update(self):
        body = UpdateProfileRequest(email="only@email.com")
        with patch("app.api.users.update_profile") as mock_update, \
             patch("app.api.users.get_profile", return_value={"id": 1, "username": "x", "email": "x@x.com", "created_at": None}):
            await update_current_user_profile(body=body, current_user={"user_id": 1, "username": "x"})

        mock_update.assert_called_once_with(1, email="only@email.com", username=None)

    async def test_returns_409_on_validation_error(self):
        body = UpdateProfileRequest(username="taken")
        current_user = {"user_id": 1, "username": "alice"}

        with patch("app.api.users.update_profile", side_effect=ValidationError("username already taken")):
            with self.assertRaises(Exception) as exc_info:
                await update_current_user_profile(body=body, current_user=current_user)

        assert getattr(exc_info.exception, "status_code", None) == 409

    async def test_no_op_when_both_fields_none(self):
        """Even if no fields change, the endpoint still re-fetches the profile."""
        body = UpdateProfileRequest()  # both None
        profile = {"id": 1, "username": "alice", "email": "alice@test.com", "created_at": None}

        with patch("app.api.users.update_profile") as mock_update, \
             patch("app.api.users.get_profile", side_effect=[profile, profile]):
            result = await update_current_user_profile(body=body, current_user={"user_id": 1, "username": "alice"})

        mock_update.assert_called_once_with(1, email=None, username=None)
        assert result.username == "alice"


# ---------------------------------------------------------------------------
# PUT /api/users/me/password
# ---------------------------------------------------------------------------

class TestChangeCurrentUserPassword(unittest.IsolatedAsyncioTestCase):
    async def test_returns_204_on_success(self):
        body = ChangePasswordRequest(current_password="old", new_password="new1234!")
        current_user = {"user_id": 1, "username": "alice"}

        with patch("app.api.users.change_password") as mock_change:
            result = await change_current_user_password(body=body, current_user=current_user)

        # FastAPI converts None-returning endpoints to the configured status_code (204)
        assert result is None
        mock_change.assert_called_once_with(
            1,
            current_password="old",
            new_password="new1234!",
        )

    async def test_returns_409_on_wrong_current_password(self):
        body = ChangePasswordRequest(current_password="wrong", new_password="new1234!")
        current_user = {"user_id": 1, "username": "alice"}

        with patch("app.api.users.change_password", side_effect=ValidationError("current password mismatch")):
            with self.assertRaises(Exception) as exc_info:
                await change_current_user_password(body=body, current_user=current_user)

        assert getattr(exc_info.exception, "status_code", None) == 409

    async def test_returns_409_on_weak_new_password(self):
        body = ChangePasswordRequest(current_password="old", new_password="x")
        current_user = {"user_id": 1, "username": "alice"}

        with patch("app.api.users.change_password", side_effect=ValidationError("password too weak")):
            with self.assertRaises(Exception) as exc_info:
                await change_current_user_password(body=body, current_user=current_user)

        assert getattr(exc_info.exception, "status_code", None) == 409
