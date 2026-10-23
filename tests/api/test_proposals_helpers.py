"""Tests para helpers internos de app/api/proposals.py.

PR #102 round 2 (Laura): estos tests estaban en
``tests/test_session_store.py`` pero testean funciones de
``app.api.proposals`` (_latest_assistant_text, _load_project_state),
no de session_store. Los movimos aca para que el archivo
coincida con el modulo que testea.

Se mueven los 9 tests:
- 4 de TestLatestAssistantText
- 5 de TestLoadProjectState
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


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
