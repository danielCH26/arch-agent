"""
HTTP-level tests for ``POST /api/projects/{id}/phase/{phase}/decision`` and
``GET /api/projects/{id}/phases`` (HU10 REQ-SA-13/14/15/19/22).

Strategy: directly call the route functions with a mocked SessionLocal,
mirroring the pattern used by ``tests/api/test_projects.py`` for the
internal ``_require_project`` helper. This exercises the Pydantic body
validation and the domain-exception → HTTP mapping without standing up the
full FastAPI app.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import projects as projects_module
from app.core import phase_decisions


# --- Helpers -----------------------------------------------------------------


def _fake_session_with_terminals(
    *,
    user_id: int = 1,
    project_id: int = 1,
    phase: str = "requerimientos",
    existing_decision=None,
    latest_proposal=None,
    session_row=None,
):
    """Return a MagicMock SQLAlchemy session with the row lookups stubbed."""
    from datetime import timedelta

    project = MagicMock()
    project.id = project_id
    project.user_id = user_id
    project.current_phase = phase
    project.phase_ready = False

    if session_row is None:
        sr = MagicMock()
        sr.id = 1
        session_row = sr

    sess = MagicMock()

    # ``add`` mutates the ORM object so the helper can read ``obj.id`` after
    # ``flush`` (mirrors what SQLAlchemy does for autoincrement PKs).
    _add_counter = {"n": 0}

    def _add(obj):
        _add_counter["n"] += 1
        if getattr(obj, "id", None) is None:
            try:
                obj.id = _add_counter["n"]
            except Exception:
                pass

    sess.add = MagicMock(side_effect=_add)
    sess.flush = MagicMock()
    sess.commit = MagicMock()
    sess.rollback = MagicMock()
    sess.close = MagicMock()

    # _FakeQuery terminal map: model -> terminal value for the next .first()
    terminals = {
        phase_decisions.Project: project,
        phase_decisions.UserSession: session_row,
        phase_decisions.Approval: existing_decision,
        phase_decisions.Proposal: latest_proposal,
    }

    def _query(model):
        q = MagicMock()
        terminal = terminals.get(model)

        # Simulate the SQL ``Approval.created_at >= cutoff`` filter so the
        # 60-second idempotency window actually drops out-of-window rows.
        def _maybe_apply(row):
            if model is phase_decisions.Approval and row is not None:
                cutoff = datetime.utcnow() - timedelta(
                    seconds=phase_decisions.IDEMPOTENCY_WINDOW_SECONDS
                )
                return row.created_at is not None and row.created_at >= cutoff
            return True

        q.filter = MagicMock(return_value=q)
        q.order_by = MagicMock(return_value=q)
        q.first = MagicMock(
            side_effect=lambda: terminal if _maybe_apply(terminal) else None
        )
        q.all = MagicMock(return_value=[] if terminal is None else terminal)
        return q

    sess.query = MagicMock(side_effect=_query)
    return sess, project


def _set_fake_sessionlocal(monkeypatch, sess):
    """Replace ``SessionLocal`` in ``app.core.database`` with a factory that
    returns the pre-built fake session. Patching the source module is
    necessary because each route function re-imports ``SessionLocal`` from
    ``app.core.database`` inside its body (mirrors the project's existing
    mock-friendly pattern)."""

    def _factory():
        return sess

    monkeypatch.setattr("app.core.database.SessionLocal", _factory)


def _patch_require_project(monkeypatch, project_id: int = 1, user_id: int = 1):
    """Bypass the ownership check (it's tested separately in test_projects)."""

    def _stub_require(uid: int, pid: int):
        proj = MagicMock()
        proj.id = pid
        proj.user_id = uid
        return proj

    monkeypatch.setattr(projects_module, "_require_project", _stub_require)


# --- 200 happy path ----------------------------------------------------------


class TestDecisionEndpointHappyPath:
    def test_approve_returns_200_with_next_phase(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="requerimientos")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        result = asyncio.run(
            projects_module.phase_decision(
                project_id=project.id,
                phase="requerimientos",
                body=projects_module.PhaseDecisionIn(action="approve"),
                current_user={"user_id": 1, "username": "architect"},
            )
        )

        assert isinstance(result, projects_module.PhaseDecisionOut)
        assert result.phase == "requerimientos"
        assert result.action == "approve"
        assert result.next_phase == "propuesta"
        assert result.idempotent is False

    def test_modify_with_feedback_returns_200(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="revision")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        result = asyncio.run(
            projects_module.phase_decision(
                project_id=project.id,
                phase="revision",
                body=projects_module.PhaseDecisionIn(
                    action="modify",
                    feedback="cambiar a event-driven",
                    payload={"patron_elegido": "Event Sourcing"},
                ),
                current_user={"user_id": 1, "username": "architect"},
            )
        )
        assert result.action == "modify"
        assert result.next_phase is None

    def test_final_approve_returns_next_phase_null(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="final")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        result = asyncio.run(
            projects_module.phase_decision(
                project_id=project.id,
                phase="final",
                body=projects_module.PhaseDecisionIn(action="approve"),
                current_user={"user_id": 1, "username": "architect"},
            )
        )
        assert result.next_phase is None


# --- Error mapping ----------------------------------------------------------


class TestDecisionEndpointErrors:
    def test_invalid_action_raises_422_via_helper(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="requerimientos")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        with pytest.raises(phase_decisions.InvalidAction):
            phase_decisions.record_decision(
                db=sess,
                project_id=project.id,
                phase="requerimientos",
                action="smash",
            )

    def test_invalid_phase_raises_422_via_helper(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="requerimientos")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        with pytest.raises(phase_decisions.InvalidPhase):
            phase_decisions.record_decision(
                db=sess,
                project_id=project.id,
                phase="bogus",
                action="approve",
            )

    def test_modify_without_feedback_raises_400(self, monkeypatch):
        sess, project = _fake_session_with_terminals(phase="revision")
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        with pytest.raises(phase_decisions.ModifyFeedbackRequired):
            phase_decisions.record_decision(
                db=sess,
                project_id=project.id,
                phase="revision",
                action="modify",
                feedback="   ",
            )

    def test_unknown_project_raises_404(self, monkeypatch):
        sess = MagicMock()
        sess.add = MagicMock()
        sess.flush = MagicMock()
        sess.commit = MagicMock()
        sess.rollback = MagicMock()
        sess.close = MagicMock()

        # Mock query so Project lookup returns None for the unknown id.
        q = MagicMock()
        q.filter = MagicMock(return_value=q)
        q.order_by = MagicMock(return_value=q)
        q.first = MagicMock(return_value=None)
        q.all = MagicMock(return_value=[])
        sess.query = MagicMock(return_value=q)

        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        with pytest.raises(phase_decisions.ProjectNotFound):
            phase_decisions.record_decision(
                db=sess,
                project_id=99999,
                phase="requerimientos",
                action="approve",
            )

    def test_conflict_returns_decision_conflict(self, monkeypatch):
        existing = MagicMock()
        existing.decision = "approved"
        existing.created_at = datetime.utcnow()  # inside the window
        sess, project = _fake_session_with_terminals(
            phase="requerimientos", existing_decision=existing
        )
        _set_fake_sessionlocal(monkeypatch, sess)
        _patch_require_project(monkeypatch)

        with pytest.raises(phase_decisions.DecisionConflict) as exc_info:
            phase_decisions.record_decision(
                db=sess,
                project_id=project.id,
                phase="requerimientos",
                action="reject",
            )
        assert exc_info.value.current_decision == "approved"
        assert exc_info.value.phase == "requerimientos"


# --- Body validation (Pydantic-level) --------------------------------------


class TestDecisionEndpointBodyValidation:
    def test_phase_decision_in_accepts_valid_body(self):
        body = projects_module.PhaseDecisionIn(action="approve")
        assert body.action == "approve"
        assert body.feedback is None
        assert body.payload is None

    def test_phase_decision_in_rejects_unknown_action(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            projects_module.PhaseDecisionIn(action="smash")

    def test_phase_decision_in_accepts_modify_with_feedback(self):
        body = projects_module.PhaseDecisionIn(
            action="modify",
            feedback="ajustar",
            payload={"patron_elegido": "Event Sourcing"},
        )
        assert body.action == "modify"
        assert body.feedback == "ajustar"
        assert body.payload == {"patron_elegido": "Event Sourcing"}


# --- GET /phases read endpoint ---------------------------------------------


class TestListPhasesEndpoint:
    def test_list_phases_returns_5_items(self, monkeypatch):
        sess = MagicMock()
        sess.add = MagicMock()
        sess.flush = MagicMock()
        sess.commit = MagicMock()
        sess.rollback = MagicMock()
        sess.close = MagicMock()

        project = MagicMock()
        project.id = 1
        project.user_id = 1
        project.current_phase = "requerimientos"
        project.phase_ready = False

        sr = MagicMock()
        sr.id = 7

        # Map model class to terminal value (None for Approval so no prior
        # decisions appear).
        from app.models.approval import Approval
        from app.models.session import UserSession

        def _query(model):
            q = MagicMock()
            if model is projects_module.Project:
                t = project
            elif model is UserSession:
                t = sr
            elif model is Approval:
                t = []
            else:
                t = None

            q.filter = MagicMock(return_value=q)
            q.order_by = MagicMock(return_value=q)
            q.first = MagicMock(return_value=t if not isinstance(t, list) else None)
            q.all = MagicMock(return_value=t if isinstance(t, list) else [])
            return q

        sess.query = MagicMock(side_effect=_query)
        _set_fake_sessionlocal(monkeypatch, sess)

        result = asyncio.run(
            projects_module.list_phases(
                project_id=1,
                current_user={"user_id": 1, "username": "architect"},
            )
        )

        assert result.current_phase == "requerimientos"
        assert len(result.phases) == 5
        # First phase is active, the others are pending (no approvals rows).
        assert result.phases[0].status == "active"
        for ph in result.phases[1:]:
            assert ph.status == "pending"
            assert ph.ready is False
            assert ph.current_decision is None