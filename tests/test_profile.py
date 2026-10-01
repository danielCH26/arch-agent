"""Tests para app.auth.profile — get_profile, update_profile, change_password."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest


class TestGetProfile:
    def test_returns_profile_dict(self):
        from app.auth.profile import get_profile

        user = MagicMock()
        user.id = 7
        user.username = "laura"
        user.email = "laura@test.com"
        user.created_at = datetime(2026, 8, 1, 0, 0, 0)

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_session.return_value = mock_db

            profile = get_profile(7)

        assert profile["id"] == 7
        assert profile["username"] == "laura"
        assert profile["email"] == "laura@test.com"
        assert profile["created_at"] == "2026-08-01T00:00:00Z"

    def test_returns_none_when_created_at_missing(self):
        from app.auth.profile import get_profile

        user = MagicMock()
        user.id = 7
        user.username = "laura"
        user.email = "laura@test.com"
        user.created_at = None

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_session.return_value = mock_db

            profile = get_profile(7)

        assert profile["created_at"] is None

    def test_user_not_found_raises_validation_error(self):
        from app.auth.profile import get_profile
        from app.auth.validators import ValidationError

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = None
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="no encontrado"):
                get_profile(999)


class TestUpdateProfile:
    def test_updates_username(self):
        from app.auth.profile import update_profile

        user = MagicMock()
        user.id = 7
        user.username = "old"
        user.email = "same@test.com"

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            # No conflict on username query
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            update_profile(7, email=None, username="new")

        assert user.username == "new"
        assert user.email == "same@test.com"
        mock_db.commit.assert_called_once()

    def test_updates_email(self):
        from app.auth.profile import update_profile

        user = MagicMock()
        user.id = 7
        user.username = "same"
        user.email = "old@test.com"

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            update_profile(7, email="new@test.com", username=None)

        assert user.email == "new@test.com"
        assert user.username == "same"

    def test_username_conflict_raises(self):
        from app.auth.profile import update_profile
        from app.auth.validators import ValidationError

        user = MagicMock()
        user.id = 7
        user.username = "old"
        user.email = "x@y.com"

        conflict = MagicMock()
        conflict.id = 99

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_db.query.return_value.filter.return_value.first.return_value = conflict
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="ya está en uso"):
                update_profile(7, email=None, username="taken")

        mock_db.rollback.assert_called_once()

    def test_email_conflict_raises(self):
        from app.auth.profile import update_profile
        from app.auth.validators import ValidationError

        user = MagicMock()
        user.id = 7
        user.username = "same"
        user.email = "old@test.com"

        conflict = MagicMock()
        conflict.id = 99

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_db.query.return_value.filter.return_value.first.return_value = conflict
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="ya está en uso"):
                update_profile(7, email="taken@test.com", username=None)

    def test_user_not_found_raises(self):
        from app.auth.profile import update_profile
        from app.auth.validators import ValidationError

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = None
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="no encontrado"):
                update_profile(999, email="x@y.com", username=None)

    def test_integrity_error_maps_to_validation_error(self):
        from sqlalchemy.exc import IntegrityError
        from app.auth.profile import update_profile
        from app.auth.validators import ValidationError

        user = MagicMock()
        user.id = 7
        user.username = "old"
        user.email = "x@y.com"

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_db.commit.side_effect = IntegrityError("UPDATE", {}, Exception())
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="ya está en uso"):
                update_profile(7, email="new@test.com", username=None)


class TestChangePassword:
    def test_changes_password_when_current_is_correct(self):
        import bcrypt as _bcrypt
        from app.auth.profile import change_password

        user = MagicMock()
        user.id = 7
        user.username = "laura"
        user.password_hash = _bcrypt.hashpw(b"Old@1234", _bcrypt.gensalt()).decode()

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_session.return_value = mock_db

            change_password(7, current_password="Old@1234", new_password="New@5678")

        # The new hash should be different from the old one
        assert user.password_hash != _bcrypt.hashpw(b"Old@1234", _bcrypt.gensalt()).decode()
        mock_db.commit.assert_called_once()

    def test_wrong_current_password_raises(self):
        import bcrypt as _bcrypt
        from app.auth.profile import change_password
        from app.auth.validators import ValidationError

        user = MagicMock()
        user.id = 7
        user.password_hash = _bcrypt.hashpw(b"correct", _bcrypt.gensalt()).decode()

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="no es correcta"):
                change_password(7, current_password="wrong", new_password="New@5678")

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    def test_weak_new_password_raises(self):
        import bcrypt as _bcrypt
        from app.auth.profile import change_password
        from app.auth.validators import ValidationError

        user = MagicMock()
        user.id = 7
        user.password_hash = _bcrypt.hashpw(b"Old@1234", _bcrypt.gensalt()).decode()

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="contrase"):
                change_password(7, current_password="Old@1234", new_password="weak")

    def test_user_not_found_raises(self):
        from app.auth.profile import change_password
        from app.auth.validators import ValidationError

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = None
            mock_session.return_value = mock_db

            with pytest.raises(ValidationError, match="no encontrado"):
                change_password(999, current_password="x", new_password="New@5678")

    def test_db_session_closed_even_on_error(self):
        import bcrypt as _bcrypt
        from app.auth.profile import change_password

        user = MagicMock()
        user.id = 7
        user.password_hash = _bcrypt.hashpw(b"Old@1234", _bcrypt.gensalt()).decode()

        with patch("app.auth.profile.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.get.return_value = user
            mock_db.commit.side_effect = RuntimeError("db boom")
            mock_session.return_value = mock_db

            with pytest.raises(RuntimeError):
                change_password(7, current_password="Old@1234", new_password="New@5678")

        mock_db.close.assert_called_once()