"""Tests for app/auth/profile.py.

Pure unit tests with full DB mocking (no real database).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import bcrypt
from sqlalchemy.exc import IntegrityError

from app.auth.profile import change_password, get_profile, update_profile
from app.auth.validators import ValidationError


def _make_user(
    user_id: int = 1,
    username: str = "alice",
    email: str = "alice@test.com",
    password_hash: str | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.email = email
    user.password_hash = password_hash or bcrypt.hashpw(b"oldpass123!", bcrypt.gensalt()).decode()
    user.created_at = created_at
    return user


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------

class TestGetProfile(unittest.TestolatedAsyncioTestCase if False else unittest.TestCase):
    """Plain unittest.TestCase — get_profile is sync."""

    def test_returns_profile_with_created_at(self):
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        user = _make_user(user_id=7, created_at=ts)
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            result = get_profile(user_id=7)

        assert result["id"] == 7
        assert result["username"] == "alice"
        assert result["email"] == "alice@test.com"
        # created_at is rendered with the trailing "Z"
        assert result["created_at"] == "2025-01-01T12:00:00+00:00Z"
        mock_db.close.assert_called_once()

    def test_returns_profile_without_created_at(self):
        user = _make_user(created_at=None)
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            result = get_profile(user_id=1)

        assert result["created_at"] is None
        mock_db.close.assert_called_once()

    def test_raises_validation_error_when_user_missing(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(ValidationError) as ctx:
                get_profile(user_id=999)

        assert "no encontrado" in str(ctx.exception).lower()
        mock_db.close.assert_called_once()

    def test_closes_db_on_exception(self):
        mock_db = MagicMock()
        mock_db.get.side_effect = RuntimeError("boom")

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(RuntimeError):
                get_profile(user_id=1)

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# update_profile
# ---------------------------------------------------------------------------

class TestUpdateProfile(unittest.TestCase):
    def test_updates_username_only(self):
        user = _make_user()
        mock_db = MagicMock()
        mock_db.get.return_value = user
        # No conflict on this query
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.auth.profile.SessionLocal", return_value=mock_db), \
             patch("app.auth.profile.validate_username", return_value="alice2"):
            result = update_profile(user_id=1, username="alice2")

        assert result == {"username": "alice2", "email": "alice@test.com"}
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()
        mock_db.close.assert_called_once()

    def test_updates_email_only(self):
        user = _make_user()
        mock_db = MagicMock()
        mock_db.get.return_value = user
        # No conflict on this query
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.auth.profile.SessionLocal", return_value=mock_db), \
             patch("app.auth.profile.validate_email_input", return_value="alice2@test.com"):
            result = update_profile(user_id=1, email="alice2@test.com")

        assert result["email"] == "alice2@test.com"
        mock_db.close.assert_called_once()

    def test_no_op_when_both_fields_none(self):
        user = _make_user()
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            result = update_profile(user_id=1)

        assert result == {"username": "alice", "email": "alice@test.com"}
        mock_db.commit.assert_called_once()

    def test_raises_when_user_missing(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(ValidationError):
                update_profile(user_id=999, username="x")

        # No commit, no rollback (no transaction started)
        mock_db.commit.assert_not_called()
        mock_db.close.assert_called_once()

    def test_raises_on_username_conflict(self):
        other = _make_user(user_id=2, username="taken")
        user = _make_user(user_id=1)

        mock_db = MagicMock()
        mock_db.get.return_value = user
        # first .get() is for our user, then .query().filter().first() returns the conflict
        mock_db.query.return_value.filter.return_value.first.return_value = other

        with patch("app.auth.profile.SessionLocal", return_value=mock_db), \
             patch("app.auth.profile.validate_username", return_value="taken"):
            with self.assertRaises(ValidationError) as ctx:
                update_profile(user_id=1, username="taken")

        assert "ya está en uso" in str(ctx.exception).lower()
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_raises_on_email_conflict(self):
        other = _make_user(user_id=2, email="taken@test.com")
        user = _make_user(user_id=1)

        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_db.query.return_value.filter.return_value.first.return_value = other

        with patch("app.auth.profile.SessionLocal", return_value=mock_db), \
             patch("app.auth.profile.validate_email_input", return_value="taken@test.com"):
            with self.assertRaises(ValidationError) as ctx:
                update_profile(user_id=1, email="taken@test.com")

        assert "ya está en uso" in str(ctx.exception).lower()
        mock_db.rollback.assert_called_once()

    def test_translates_integrity_error_to_validation_error(self):
        """A DB IntegrityError on commit must be caught and raised as ValidationError."""
        user = _make_user()
        mock_db = MagicMock()
        mock_db.get.return_value = user
        mock_db.commit.side_effect = IntegrityError("INSERT", {}, Exception("dup"))

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(ValidationError) as ctx:
                update_profile(user_id=1, username="alice2")

        assert "ya está en uso" in str(ctx.exception).lower()
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# change_password
# ---------------------------------------------------------------------------

class TestChangePassword(unittest.TestCase):
    def test_changes_password_when_current_correct(self):
        old_hash = bcrypt.hashpw(b"oldpass123!", bcrypt.gensalt()).decode()
        user = _make_user(password_hash=old_hash)
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            change_password(user_id=1, current_password="oldpass123!", new_password="Newpass456!")

        # user.password_hash must have been updated
        assert user.password_hash != old_hash
        assert bcrypt.checkpw(b"Newpass456!", user.password_hash.encode())
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_rejects_wrong_current_password(self):
        old_hash = bcrypt.hashpw(b"oldpass123!", bcrypt.gensalt()).decode()
        user = _make_user(password_hash=old_hash)
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(ValidationError) as ctx:
                change_password(user_id=1, current_password="wrongpass", new_password="newpass456!")

        assert "actual no es correcta" in str(ctx.exception).lower()
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_rejects_weak_new_password(self):
        old_hash = bcrypt.hashpw(b"oldpass123!", bcrypt.gensalt()).decode()
        user = _make_user(password_hash=old_hash)
        mock_db = MagicMock()
        mock_db.get.return_value = user

        with patch("app.auth.profile.SessionLocal", return_value=mock_db), \
             patch("app.auth.profile.validate_password", side_effect=ValidationError("too weak")):
            with self.assertRaises(ValidationError):
                change_password(user_id=1, current_password="oldpass123!", new_password="x")

        mock_db.rollback.assert_called_once()

    def test_raises_when_user_missing(self):
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch("app.auth.profile.SessionLocal", return_value=mock_db):
            with self.assertRaises(ValidationError) as ctx:
                change_password(user_id=999, current_password="x", new_password="y")

        assert "no encontrado" in str(ctx.exception).lower()
        mock_db.close.assert_called_once()