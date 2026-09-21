"""
Tests for app/core/phase_decisions.py — the HU10 per-phase decision helper.

Strategy: MagicMock for the SQLAlchemy session, mirroring the pattern used
by ``tests/api/test_projects.py`` and ``tests/api/test_proposals.py``. This
keeps the helper testable without docker-compose and without SQLAlchemy's
JSONB ↔ SQLite type mismatch (we don't need the DDL at all when the
session is a Mock).

Coverage (per tasks.md §3 verification matrix):
  - 5 phases × 3 actions = 15 happy paths
  - dual-write to proposal_approvals for ``propuesta`` only (REQ-SA-17)
  - 409 conflict on different-action inside the 60s window (REQ-SA-9)
  - 200 idempotent on identical-action inside the 60s window (REQ-SA-10)
  - ``previous_output`` shape per phase (REQ-SA-16)
  - ``next_phase`` is None for ``final`` approve (REQ-SA-15.1)
  - validation: invalid phase / action / missing feedback / unknown project
  - audit row written to interaction_logs for every decision
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.core import phase_decisions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Minimal stand-in for the chainable ``db.query(...).filter(...).first()``
    returned by SQLAlchemy. Each method returns the next stub in the chain
    so tests can pre-load a value at the end of the chain."""

    def __init__(self, terminal=None, filter_fn=None, session=None):
        self._terminal = terminal
        self._filter_fn = filter_fn
        self._session = session
        self.calls: list = []

    def filter(self, *args, **kwargs):
        self.calls.append(("filter", args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        self.calls.append(("order_by", args, kwargs))
        return self

    def first(self):
        self.calls.append(("first", None, None))
        # Apply the filter so SQL semantics like ``created_at >= cutoff``
        # actually drop out-of-window rows.
        if self._filter_fn is not None and self._terminal is not None:
            return self._terminal if self._filter_fn(self._terminal) else None
        return self._terminal

    def all(self):
        self.calls.append(("all", None, None))
        return self._terminal if isinstance(self._terminal, list) else []


class _FakeSession:
    """Records every ``add``, ``flush``, ``commit``, ``rollback`` call and
    returns a per-method ``_FakeQuery`` that resolves to whatever the test
    stashed via ``set_query_terminal``.
    """

    def __init__(self) -> None:
        self.adds: list = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0
        # _query_terminals maps ``(model, attr)`` -> terminal value returned
        # by the next ``first()`` call. Tests pre-load this to simulate the
        # DB row that the helper would fetch.
        self._query_terminals: dict[tuple, object] = {}
        # _query_filters maps ``(model, attr)`` -> callable(approval_like) -> bool
        # so tests can simulate SQL filter clauses (e.g. ``created_at >= cutoff``).
        self._query_filters: dict[tuple, callable] = {}

    def set_query_terminal(self, model, attr, value) -> None:
        self._query_terminals[(model.__name__, attr)] = value

    def set_query_filter(self, model, attr, fn) -> None:
        """Filter applied to the terminal value at ``.first()`` time."""
        self._query_filters[(model.__name__, attr)] = fn

    def query(self, model):
        self._last_model = model
        return _FakeQuery(
            terminal=self._query_terminals.get((model.__name__, "default")),
            filter_fn=self._query_filters.get((model.__name__, "default")),
            session=self,
        )

    def add(self, obj) -> None:
        self.adds.append(obj)
        # If the helper later calls ``db.flush()`` it relies on ``id`` being
        # populated on ORM objects — simulate that.
        if getattr(obj, "id", None) is None:
            try:
                obj.id = len(self.adds)  # type: ignore[attr-defined]
            except Exception:
                pass

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _make_session(
    *,
    user_id: int = 1,
    project_id: int = 1,
    phase: str = "requerimientos",
    existing_decision=None,
    latest_proposal=None,
    session_row=None,
):
    """Build a _FakeSession with sensible defaults for a single-user project.

    Tests override individual ``set_query_terminal`` slots when they need
    different fixtures (e.g. multiple existing decisions, missing proposal).
    """
    from datetime import datetime, timedelta

    project = MagicMock()
    project.id = project_id
    project.user_id = user_id
    project.current_phase = phase
    project.phase_ready = False

    sess = _FakeSession()
    if session_row is None:
        sr = MagicMock()
        sr.id = 1
        session_row = sr
    sess.set_query_terminal(phase_decisions.Project, "default", project)
    sess.set_query_terminal(phase_decisions.UserSession, "default", session_row)
    sess.set_query_terminal(phase_decisions.Approval, "default", existing_decision)
    sess.set_query_terminal(phase_decisions.Proposal, "default", latest_proposal)

    # Simulate the SQL ``Approval.created_at >= cutoff`` filter so the
    # 60-second idempotency window actually drops out-of-window rows.
    cutoff = datetime.utcnow() - timedelta(seconds=phase_decisions.IDEMPOTENCY_WINDOW_SECONDS)

    def _approval_in_window(row):
        return getattr(row, "created_at", None) is not None and row.created_at >= cutoff

    sess.set_query_filter(phase_decisions.Approval, "default", _approval_in_window)

    return sess, project


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_available_phases_has_five_entries(self):
        assert phase_decisions.AVAILABLE_PHASES == [
            "requerimientos",
            "propuesta",
            "refinamiento",
            "revision",
            "final",
        ]

    def test_decision_to_db_uses_participles(self):
        assert phase_decisions.DECISION_TO_DB == {
            "approve": "approved",
            "modify": "modified",
            "reject": "rejected",
        }


# ---------------------------------------------------------------------------
# Happy paths: 5 phases × 3 actions
# ---------------------------------------------------------------------------


class TestHappyPaths:
    @pytest.mark.parametrize(
        "phase",
        ["requerimientos", "propuesta", "refinamiento", "revision", "final"],
    )
    @pytest.mark.parametrize("action", ["approve", "modify", "reject"])
    def test_record_decision_returns_result_with_action_and_phase(
        self, phase, action
    ):
        db, project = _make_session(phase=phase)
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase=phase,
            action=action,
            feedback="ok" if action == "modify" else None,
        )

        assert result.action == action
        assert result.phase == phase
        assert result.project_id == project.id
        assert result.idempotent is False
        assert result.decision_id > 0
        # Exactly one ``approvals`` add + one ``interaction_logs`` add per call.
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        audits = [a for a in db.adds if isinstance(a, phase_decisions.InteractionLog)]
        assert len(approvals) == 1
        assert len(audits) == 1
        assert approvals[0].decision == phase_decisions.DECISION_TO_DB[action]
        assert approvals[0].phase == phase
        assert audits[0].action_type == action
        assert audits[0].phase == phase

    @pytest.mark.parametrize(
        "phase",
        ["requerimientos", "propuesta", "refinamiento", "revision", "final"],
    )
    def test_approve_sets_phase_ready_true(self, phase):
        db, project = _make_session(phase=phase, user_id=2)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase=phase, action="approve"
        )
        assert project.phase_ready is True

    @pytest.mark.parametrize(
        "phase",
        ["requerimientos", "propuesta", "refinamiento", "revision", "final"],
    )
    def test_reject_resets_phase_ready_false(self, phase):
        db, project = _make_session(phase=phase, user_id=3)
        project.phase_ready = True  # simulate pre-rejected state
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase=phase, action="reject"
        )
        assert project.phase_ready is False

    @pytest.mark.parametrize(
        "phase",
        ["requerimientos", "propuesta", "refinamiento", "revision", "final"],
    )
    def test_modify_leaves_phase_ready_unchanged(self, phase):
        db, project = _make_session(phase=phase, user_id=4)
        project.phase_ready = True  # was ready before modify
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase=phase,
            action="modify",
            feedback="please adjust",
        )
        # Modify does not change phase_ready: the user is still iterating.
        assert project.phase_ready is True


# ---------------------------------------------------------------------------
# next_phase semantics (REQ-SA-15.1)
# ---------------------------------------------------------------------------


class TestNextPhase:
    def test_final_approve_returns_next_phase_none(self):
        db, project = _make_session(phase="final", user_id=20)
        result = phase_decisions.record_decision(
            db=db, project_id=project.id, phase="final", action="approve"
        )
        assert result.next_phase is None

    def test_approve_returns_next_phase_in_order(self):
        db, project = _make_session(phase="requerimientos", user_id=21)
        result = phase_decisions.record_decision(
            db=db, project_id=project.id, phase="requerimientos", action="approve"
        )
        assert result.next_phase == "propuesta"

    def test_propuesta_approve_returns_refinamiento(self):
        db, project = _make_session(phase="propuesta", user_id=22)
        result = phase_decisions.record_decision(
            db=db, project_id=project.id, phase="propuesta", action="approve"
        )
        assert result.next_phase == "refinamiento"

    def test_reject_returns_next_phase_none(self):
        db, project = _make_session(phase="propuesta", user_id=23)
        result = phase_decisions.record_decision(
            db=db, project_id=project.id, phase="propuesta", action="reject"
        )
        assert result.next_phase is None

    def test_modify_returns_next_phase_none(self):
        db, project = _make_session(phase="revision", user_id=24)
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="revision",
            action="modify",
            feedback="change to event-driven",
            payload={"patron_elegido": "Event Sourcing"},
        )
        assert result.next_phase is None


# ---------------------------------------------------------------------------
# Dual-write (REQ-SA-17 / REQ-PA-HU10-1)
# ---------------------------------------------------------------------------


class TestDualWrite:
    def test_propuesta_approve_dual_writes_when_proposal_exists(self):
        latest = MagicMock()
        latest.id = 42
        latest.content = {"summary": "demo"}
        latest.citations = []
        latest.iteration = 1
        db, project = _make_session(phase="propuesta", user_id=30, latest_proposal=latest)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="propuesta", action="approve"
        )
        pa = [a for a in db.adds if isinstance(a, phase_decisions.ProposalApproval)]
        assert len(pa) == 1
        assert pa[0].decision == "approved"
        assert pa[0].proposal_id == 42
        assert pa[0].previous_output == {
            "content": {"summary": "demo"},
            "citations": [],
            "iteration": 1,
        }

    def test_propuesta_skips_dual_write_when_no_proposal(self):
        db, project = _make_session(phase="propuesta", user_id=31, latest_proposal=None)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="propuesta", action="approve"
        )
        pa = [a for a in db.adds if isinstance(a, phase_decisions.ProposalApproval)]
        assert pa == []

    def test_non_propuesta_does_not_dual_write(self):
        latest = MagicMock()
        latest.id = 99
        db, project = _make_session(phase="requerimientos", user_id=32, latest_proposal=latest)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="requerimientos", action="approve"
        )
        pa = [a for a in db.adds if isinstance(a, phase_decisions.ProposalApproval)]
        assert pa == []


# ---------------------------------------------------------------------------
# Concurrency: 409 on second different-action decision in window
# ---------------------------------------------------------------------------


class TestConflict:
    def test_second_different_action_in_window_raises_conflict(self):
        existing = MagicMock()
        existing.decision = "approved"
        existing.created_at = datetime.utcnow() - timedelta(seconds=10)
        db, project = _make_session(
            phase="requerimientos", user_id=40, existing_decision=existing
        )
        with pytest.raises(phase_decisions.DecisionConflict) as exc_info:
            phase_decisions.record_decision(
                db=db,
                project_id=project.id,
                phase="requerimientos",
                action="reject",
            )
        assert exc_info.value.current_decision == "approved"
        assert exc_info.value.phase == "requerimientos"

    def test_second_identical_action_in_window_returns_idempotent(self):
        existing = MagicMock()
        existing.id = 7
        existing.decision = "approved"
        existing.created_at = datetime.utcnow() - timedelta(seconds=10)
        db, project = _make_session(
            phase="requerimientos", user_id=41, existing_decision=existing
        )
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="approve",
        )
        assert result.idempotent is True
        assert result.decision_id == 7

    def test_decision_outside_window_is_accepted(self):
        existing = MagicMock()
        existing.decision = "approved"
        existing.created_at = datetime.utcnow() - timedelta(seconds=120)
        db, project = _make_session(
            phase="requerimientos", user_id=42, existing_decision=existing
        )
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="reject",
        )
        assert result.idempotent is False


# ---------------------------------------------------------------------------
# previous_output shape per phase (REQ-SA-3, REQ-SA-16)
# ---------------------------------------------------------------------------


class TestPreviousOutput:
    def test_revision_carries_tradeoffs_payload(self):
        db, project = _make_session(phase="revision", user_id=50)
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="revision",
            action="modify",
            feedback="cambiar a event-driven",
            payload={
                "patron_elegido": "Event Sourcing",
                "ventajas": ["audit", "replay"],
                "desventajas": ["complexity"],
            },
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {
            "patron_elegido": "Event Sourcing",
            "ventajas": ["audit", "replay"],
            "desventajas": ["complexity"],
        }

    def test_revision_defaults_missing_tradeoffs_to_empty(self):
        db, project = _make_session(phase="revision", user_id=51)
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="revision",
            action="modify",
            feedback="ajustar",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {
            "patron_elegido": "",
            "ventajas": [],
            "desventajas": [],
        }

    def test_final_approve_has_empty_previous_output(self):
        db, project = _make_session(phase="final", user_id=52)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="final", action="approve"
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {}

    def test_propuesta_approve_carries_proposal_snapshot(self):
        latest = MagicMock()
        latest.id = 5
        latest.content = {"summary": "use event-driven"}
        latest.citations = [{"pattern_id": 1}]
        latest.iteration = 2
        db, project = _make_session(phase="propuesta", user_id=53, latest_proposal=latest)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="propuesta", action="approve"
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {
            "content": {"summary": "use event-driven"},
            "citations": [{"pattern_id": 1}],
            "iteration": 2,
        }


# ---------------------------------------------------------------------------
# Validation errors (REQ-SA-5, REQ-SA-14.1, REQ-SA-13.2)
# ---------------------------------------------------------------------------


class TestValidation:
    def test_invalid_phase_raises(self):
        db, project = _make_session(phase="requerimientos", user_id=60)
        with pytest.raises(phase_decisions.InvalidPhase):
            phase_decisions.record_decision(
                db=db,
                project_id=project.id,
                phase="not_a_phase",
                action="approve",
            )

    def test_invalid_action_raises(self):
        db, project = _make_session(phase="requerimientos", user_id=61)
        with pytest.raises(phase_decisions.InvalidAction):
            phase_decisions.record_decision(
                db=db,
                project_id=project.id,
                phase="requerimientos",
                action="smash",
            )

    def test_modify_without_feedback_raises(self):
        db, project = _make_session(phase="revision", user_id=62)
        with pytest.raises(phase_decisions.ModifyFeedbackRequired):
            phase_decisions.record_decision(
                db=db,
                project_id=project.id,
                phase="revision",
                action="modify",
                feedback="   ",
            )

    def test_unknown_project_raises_not_found(self):
        db = _FakeSession()
        db.set_query_terminal(phase_decisions.Project, "default", None)
        with pytest.raises(phase_decisions.ProjectNotFound):
            phase_decisions.record_decision(
                db=db,
                project_id=99999,
                phase="requerimientos",
                action="approve",
            )


# ---------------------------------------------------------------------------
# Audit row (interaction_logs)
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_audit_row_inserted_for_every_decision(self):
        db, project = _make_session(phase="requerimientos", user_id=70)
        phase_decisions.record_decision(
            db=db, project_id=project.id, phase="requerimientos", action="approve"
        )
        audits = [a for a in db.adds if isinstance(a, phase_decisions.InteractionLog)]
        assert len(audits) == 1
        assert audits[0].phase == "requerimientos"
        assert audits[0].action_type == "approve"


# ---------------------------------------------------------------------------
# get_latest_decision helper
# ---------------------------------------------------------------------------


class TestGetLatestDecision:
    def test_returns_none_when_no_project(self):
        db = _FakeSession()
        db.set_query_terminal(phase_decisions.Project, "default", None)
        assert phase_decisions.get_latest_decision(db, 999, "requerimientos") is None

    def test_returns_none_when_no_session(self):
        db = _FakeSession()
        db.set_query_terminal(phase_decisions.Project, "default", MagicMock())
        db.set_query_terminal(phase_decisions.UserSession, "default", None)
        assert phase_decisions.get_latest_decision(db, 1, "requerimientos") is None

    def test_returns_approval_row(self):
        existing = MagicMock()
        existing.decision = "approved"
        existing.created_at = datetime.utcnow() - timedelta(seconds=10)
        db, project = _make_session(
            phase="requerimientos", user_id=80, existing_decision=existing
        )
        result = phase_decisions.get_latest_decision(
            db, project.id, "requerimientos"
        )
        assert result is existing