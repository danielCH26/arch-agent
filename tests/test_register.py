"""Tests para app.auth.register — register_user."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


class TestRegisterUserSuccess:
    def test_register_user_creates_record_with_hashed_password(self):
        from app.auth.register import register_user

        user_in_db = MagicMock()
        user_in_db.id = 42
        user_in_db.username = "newuser"
        user_in_db.email = "new@test.com"

        def fake_refresh(u):
            u.id = 42
            u.username = "newuser"
            u.email = "new@test.com"

        with patch("app.auth.register.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.refresh.side_effect = fake_refresh
            mock_session.return_value = mock_db

            user = register_user("newuser", "new@test.com", "Test@1234")

        assert user.id == 42
        assert user.username == "newuser"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        # Password should be hashed, not stored in plaintext
        added_user = mock_db.add.call_args[0][0]
        assert added_user.password_hash != "Test@1234"
        assert added_user.password_hash.startswith("$2b$")  # bcrypt prefix


class TestRegisterUserValidationErrors:
    def test_invalid_username_raises_validation_error(self):
        from app.auth.register import register_user
        from app.auth.validators import ValidationError

        with pytest.raises(ValidationError, match="username"):
            register_user("", "new@test.com", "Test@1234")

    def test_invalid_email_raises_validation_error(self):
        from app.auth.register import register_user
        from app.auth.validators import ValidationError

        with pytest.raises(ValidationError, match="email"):
            register_user("newuser", "not-an-email", "Test@1234")

    def test_invalid_password_raises_validation_error(self):
        from app.auth.register import register_user
        from app.auth.validators import ValidationError

        with pytest.raises(ValidationError, match="contrase"):
            register_user("newuser", "new@test.com", "weak")


class TestRegisterUserDBErrors:
    def test_integrity_error_maps_to_validation_error(self):
        from sqlalchemy.exc import IntegrityError
        from app.auth.register import register_user
        from app.auth.validators import ValidationError

        with patch("app.auth.register.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.commit.side_effect = IntegrityError("INSERT", {}, Exception())
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="ya está registrado"):
                register_user("newuser", "new@test.com", "Test@1234")

        mock_db.rollback.assert_called_once()

    def test_generic_db_error_propagates_and_rolls_back(self):
        from app.auth.register import register_user

        with patch("app.auth.register.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.commit.side_effect = RuntimeError("db exploded")
            mock_session.return_value = mock_db

            with pytest.raises(RuntimeError, match="db exploded"):
                register_user("newuser", "new@test.com", "Test@1234")

        mock_db.rollback.assert_called_once()

    def test_db_session_always_closed(self):
        """db.close() must run in the finally block even when commit raises."""
        from app.auth.register import register_user
        from sqlalchemy.exc import IntegrityError

        with patch("app.auth.register.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.commit.side_effect = IntegrityError("INSERT", {}, Exception())
            mock_session.return_value = mock_db

            with pytest.raises(Exception):
                register_user("newuser", "new@test.com", "Test@1234")

        mock_db.close.assert_called_once()