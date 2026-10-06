"""Tests para app.core.session_store — save/load session + diagram decisions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest


class TestSaveSessionState:
    def test_creates_session_if_missing(self):
        from app.core.session_store import save_session_state

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            save_session_state(
                user_id=1, project_id=5, active_phase="propuesta"
            )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.user_id == 1
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_updates_existing_session(self):
        from app.core.session_store import save_session_state

        user_session = MagicMock()
        user_session.user_id = 7
        user_session.project_id = None
        user_session.active_phase = None
        user_session.engram_state = None

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = user_session
            mock_session.return_value = mock_db

            save_session_state(
                user_id=7,
                project_id=42,
                active_phase="refinamiento",
                engram_state={"key": "value"},
            )

        # No new session added
        mock_db.add.assert_not_called()
        # Existing session updated
        assert user_session.project_id == 42
        assert user_session.active_phase == "refinamiento"
        assert user_session.engram_state == {"key": "value"}
        mock_db.commit.assert_called_once()

    def test_only_updates_provided_args_others_preserved(self):
        """If project_id is None, do not overwrite existing project_id."""
        from app.core.session_store import save_session_state

        user_session = MagicMock()
        user_session.user_id = 7
        user_session.project_id = 99  # already set
        user_session.active_phase = "requerimientos"
        user_session.engram_state = {"old": True}

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = user_session
            mock_session.return_value = mock_db

            save_session_state(
                user_id=7,
                active_phase="propuesta",
            )

        # project_id preserved (not overwritten with None)
        assert user_session.project_id == 99
        # active_phase updated
        assert user_session.active_phase == "propuesta"
        # engram_state preserved
        assert user_session.engram_state == {"old": True}

    def test_rollback_on_exception(self):
        from app.core.session_store import save_session_state

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.commit.side_effect = RuntimeError("db boom")
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            with pytest.raises(RuntimeError, match="db boom"):
                save_session_state(user_id=1)

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


class TestLoadSessionState:
    def test_returns_none_when_no_session(self):
        from app.core.session_store import load_session_state

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_session.return_value = mock_db

            assert load_session_state(user_id=999) is None

        mock_db.close.assert_called_once()

    def test_returns_session_fields(self):
        from app.core.session_store import load_session_state

        session = MagicMock()
        session.project_id = 5
        session.active_phase = "propuesta"
        session.engram_state = {"phase_data": "proposal_text"}

        with patch("app.core.session_store.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = session
            mock_session.return_value = mock_db

            state = load_session_state(user_id=1)

        assert state == {
            "project_id": 5,
            "active_phase": "propuesta",
            "engram_state": {"phase_data": "proposal_text"},
        }


class TestDecisionMappings:
    def test_decision_to_db_maps_approve_modify_reject(self):
        from app.core.session_store import DECISION_TO_DB

        assert DECISION_TO_DB["approve"] == "approved"
        assert DECISION_TO_DB["modify"] == "modified"
        assert DECISION_TO_DB["reject"] == "rejected"

    def test_decision_from_db_is_inverse_of_to_db(self):
        from app.core.session_store import DECISION_TO_DB, DECISION_FROM_DB

        # Every value in TO_DB has an inverse in FROM_DB
        for api_decision, db_decision in DECISION_TO_DB.items():
            assert DECISION_FROM_DB[db_decision] == api_decision


class TestLatestAssistantText:
    def test_returns_none_when_no_message(self):
        from app.api.proposals import _latest_assistant_text

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        assert _latest_assistant_text(db, session_id=1, project_id=5, user_id=1) is None

    def test_returns_stripped_content(self):
        from app.api.proposals import _latest_assistant_text

        msg = MagicMock()
        msg.content = "  hello world  "

        db = MagicMock()
        # The query chain: filter(...).order_by(desc, desc).first()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = msg

        result = _latest_assistant_text(db, session_id=1, project_id=5, user_id=1)
        assert result == "hello world"

    def test_returns_none_for_empty_content(self):
        from app.api.proposals import _latest_assistant_text

        msg = MagicMock()
        msg.content = "   "

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = msg

        assert _latest_assistant_text(db, session_id=1, project_id=5, user_id=1) is None

    def test_returns_none_for_none_content(self):
        from app.api.proposals import _latest_assistant_text

        msg = MagicMock()
        msg.content = None

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = msg

        assert _latest_assistant_text(db, session_id=1, project_id=5, user_id=1) is None


class TestLoadProjectState:
    def test_returns_empty_for_none_session(self):
        from app.api.proposals import _load_project_state

        engram, project = _load_project_state(None, project_id=5)
        assert engram == {}
        assert project == {}

    def test_returns_empty_for_none_engram_state(self):
        from app.api.proposals import _load_project_state

        session = MagicMock()
        session.engram_state = None

        engram, project = _load_project_state(session, project_id=5)
        assert engram == {}
        assert project == {}

    def test_returns_empty_when_project_state_is_empty(self):
        from app.api.proposals import _load_project_state

        session = MagicMock()
        session.engram_state = {"7": {}}

        engram, project = _load_project_state(session, project_id=5)
        assert engram == {"7": {}}
        assert project == {}

    def test_returns_project_state_when_present(self):
        from app.api.proposals import _load_project_state

        session = MagicMock()
        session.engram_state = {"5": {"propuesta": "my snapshot"}}

        engram, project = _load_project_state(session, project_id=5)
        assert engram == {"5": {"propuesta": "my snapshot"}}
        assert project == {"propuesta": "my snapshot"}

    def test_returns_empty_when_project_state_is_not_dict(self):
        from app.api.proposals import _load_project_state

        session = MagicMock()
        session.engram_state = {"5": ["corrupt", "data"]}

        engram, project = _load_project_state(session, project_id=5)
        assert engram == {"5": ["corrupt", "data"]}
        assert project == {}