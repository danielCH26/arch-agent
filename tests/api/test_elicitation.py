"""Tests for the HU11 (REQ-SA-28) past-phase guard on ``/elicitation/decision``.

Pre-HU11 behaviour: ``decide_elicitation`` accepted the body and then
clobbered ``engram_state[<pid>]["requerimientos"]["resumen"]`` on
``modify`` even when ``project.current_phase != "requerimientos"`` — so
a legacy caller (e.g. an outdated frontend build) could destroy the
elicitation state once the project had moved to ``propuesta``. HU11
adds a 409 guard that fires before any DB mutation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import elicitation as elicitation_module


def _patch_require_project(monkeypatch, project):
    """Bypass the ownership pre-flight and inject a Project with the
    ``current_phase`` the test wants to exercise."""

    def _stub_require(uid, pid):
        return project

    monkeypatch.setattr(elicitation_module, "_require_project", _stub_require)


def _patch_session_local(monkeypatch, sess):
    monkeypatch.setattr(
        "app.core.database.SessionLocal", lambda: sess
    )


class TestElicitationPastPhaseGuard:
    """REQ-SA-28 / SCN-SA-28.1 — past-phase F05 modify returns 409."""

    def test_past_phase_returns_409(self, monkeypatch):
        # current_phase="propuesta" → requerimientos is past; F05 must 409.
        project = MagicMock()
        project.id = 1
        project.user_id = 1
        project.current_phase = "propuesta"
        _patch_require_project(monkeypatch, project)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                elicitation_module.decide_elicitation(
                    project_id=1,
                    body=elicitation_module.ElicitationDecisionIn(
                        decision="modify", feedback="cambiar X"
                    ),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 409
        assert "regenerate" in str(exc_info.value.detail).lower()

    @pytest.mark.parametrize(
        "past_phase",
        ["propuesta", "refinamiento", "revision", "final"],
    )
    def test_any_past_phase_returns_409(self, monkeypatch, past_phase):
        project = MagicMock()
        project.id = 7
        project.user_id = 2
        project.current_phase = past_phase
        _patch_require_project(monkeypatch, project)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                elicitation_module.decide_elicitation(
                    project_id=7,
                    body=elicitation_module.ElicitationDecisionIn(
                        decision="approve"
                    ),
                    current_user={"user_id": 2, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 409

    def test_current_phase_still_works(self, monkeypatch):
        # SCN-SA-28.2: when current_phase == "requerimientos", the legacy
        # contract is preserved — the guard does NOT fire. We don't run
        # the whole decision path (that would need a full DB), but we
        # assert the guard does NOT raise. The downstream session lookup
        # eventually fails (HTTPException 500 from the route's broad catch),
        # but the failure MUST NOT be a 409.
        project = MagicMock()
        project.id = 1
        project.user_id = 1
        project.current_phase = "requerimientos"
        _patch_require_project(monkeypatch, project)

        # The guard passes — the function will then attempt SessionLocal
        # which we stub to return a session that fails fast. We assert
        # the failure is from downstream, not the guard (i.e. NOT a 409).
        sess = MagicMock()
        sess.query = MagicMock(side_effect=RuntimeError("session-stub-fail"))
        sess.close = MagicMock()
        _patch_session_local(monkeypatch, sess)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                elicitation_module.decide_elicitation(
                    project_id=1,
                    body=elicitation_module.ElicitationDecisionIn(
                        decision="approve"
                    ),
                    current_user={"user_id": 1, "username": "architect"},
                )
            )
        # Guard did NOT fire — the failure is downstream (500), not 409.
        assert exc_info.value.status_code != 409

    def test_guard_fires_before_engram_state_clobber(self, monkeypatch):
        # Defensive: the guard must short-circuit BEFORE the F05 modify
        # branch wipes ``engram_state``. We assert no SessionLocal access.
        project = MagicMock()
        project.id = 5
        project.user_id = 3
        project.current_phase = "final"
        _patch_require_project(monkeypatch, project)

        session_local_called = {"n": 0}

        def _sentinel():
            session_local_called["n"] += 1
            raise AssertionError(
                "SessionLocal must not be opened when guard 409s"
            )

        monkeypatch.setattr("app.core.database.SessionLocal", _sentinel)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                elicitation_module.decide_elicitation(
                    project_id=5,
                    body=elicitation_module.ElicitationDecisionIn(
                        decision="modify", feedback="x"
                    ),
                    current_user={"user_id": 3, "username": "architect"},
                )
            )
        assert exc_info.value.status_code == 409
        assert session_local_called["n"] == 0


class TestElicitationBodyValidation:
    """F05 body validation stays unchanged — guard is additive only."""

    def test_modify_body_shape(self):
        # Note: Pydantic accepts ``decision="modify"`` without ``feedback``
        # because the empty-feedback check lives at the route level (it
        # raises HTTP 400, not a Pydantic ValidationError). This is the
        # pre-HU11 contract and HU11 preserves it.
        body = elicitation_module.ElicitationDecisionIn(decision="modify")
        assert body.decision == "modify"
        assert body.feedback is None

    def test_approve_body_shape(self):
        body = elicitation_module.ElicitationDecisionIn(decision="approve")
        assert body.decision == "approve"
        assert body.feedback is None