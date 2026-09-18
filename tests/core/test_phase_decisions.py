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


# ---------------------------------------------------------------------------
# Past-phase modify (HU11 REQ-SA-27)
#
# HU10's ``_make_session`` fixture sets ``project.current_phase = phase`` in
# every test (line 141) — which HIDES the cross-phase correctness gap that
# HU11 closes. ``TestPastPhaseModify`` is the FIRST set of tests where the
# project's current phase DIFFERS from the phase being modified. Each test
# also builds the cross-phase fixtures that ``_build_previous_output``
# needs to read (engram_state, messages.attachments).
# ---------------------------------------------------------------------------


def _make_past_phase_session(
    *,
    user_id: int,
    project_id: int,
    target_phase: str,
    current_phase: str,
    elicitation_resumen: dict | None = None,
    latest_attachments: list[dict] | None = None,
    latest_proposal: object | None = None,
    session_row: object | None = None,
):
    """Build a session where ``current_phase != target_phase``.

    The fake ``_FakeQuery`` defaults to terminal=None, so the helpers
    ``_load_elicitation_resumen`` and ``_latest_assistant_attachments``
    only return a value if we explicitly wire their terminals.

    Note we also add the terminal keys for ``Project`` (current_phase
    override) so the helper's ``db.query(Project).filter(...)`` chain
    finds the project row in past-phase tests.
    """
    from app.models.message import Message

    project = MagicMock()
    project.id = project_id
    project.user_id = user_id
    project.current_phase = current_phase
    project.phase_ready = False

    if session_row is None:
        # Build a session_row that carries engram_state for ``requerimientos``
        # if a resumen was supplied — keeps the helper side-effect free.
        sr = MagicMock()
        sr.id = 1
        if elicitation_resumen is not None:
            sr.engram_state = {
                str(project_id): {"requerimientos": {"resumen": elicitation_resumen}}
            }
        else:
            sr.engram_state = {}
        session_row = sr

    sess = _FakeSession()
    sess.set_query_terminal(phase_decisions.Project, "default", project)
    sess.set_query_terminal(phase_decisions.UserSession, "default", session_row)
    # No existing decision — every test below starts from a clean window.
    sess.set_query_terminal(phase_decisions.Approval, "default", None)
    sess.set_query_terminal(phase_decisions.Proposal, "default", latest_proposal)
    # ``Message`` terminal: MagicMock with the attachments list applied.
    msg_terminal = MagicMock()
    msg_terminal.attachments = latest_attachments if latest_attachments is not None else None
    sess.set_query_terminal(Message, "default", msg_terminal)

    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(
        seconds=phase_decisions.IDEMPOTENCY_WINDOW_SECONDS
    )

    def _in_window(row):
        return getattr(row, "created_at", None) is not None and row.created_at >= cutoff

    sess.set_query_filter(phase_decisions.Approval, "default", _in_window)

    return sess, project


class TestPastPhaseModify:
    """HU11 REQ-SA-27 + REQ-SA-5: decisions on past phases are valid AND
    ``previous_output`` is now populated for ``requerimientos`` and
    ``refinamiento`` (previously empty)."""

    def test_modify_past_requerimientos_records_audit_row(self):
        # current_phase=propuesta (project is past requerimientos).
        db, project = _make_past_phase_session(
            user_id=90,
            project_id=42,
            target_phase="requerimientos",
            current_phase="propuesta",
            elicitation_resumen={"problema": "x", "usuarios": "y"},
        )
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="modify",
            feedback="falta no funcionales",
        )
        assert result.phase == "requerimientos"
        assert result.action == "modify"
        # The audit row goes into ``approvals`` AND ``interaction_logs``;
        # both must be present even on a past-phase modify.
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        audits = [a for a in db.adds if isinstance(a, phase_decisions.InteractionLog)]
        assert len(approvals) == 1
        assert len(audits) == 1
        assert audits[0].phase == "requerimientos"
        assert audits[0].action_type == "modify"

    def test_modify_past_requerimientos_snapshots_resumen(self):
        # REQ-SA-27.1: engram_state[<pid>]["requerimientos"]["resumen"]
        # becomes ``previous_output["resumen"]``.
        resumen = {
            "problema": "Sistema de reservas",
            "usuarios": "Recepcionistas",
            "funcionalidades": ["calendario", "pagos"],
            "restricciones": ["multi-tenant"],
            "calidad": ["99.9% uptime"],
        }
        db, project = _make_past_phase_session(
            user_id=91,
            project_id=7,
            target_phase="requerimientos",
            current_phase="propuesta",
            elicitation_resumen=resumen,
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="modify",
            feedback="agregar no funcionales",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {"resumen": resumen}

    def test_modify_past_requerimientos_missing_resumen_returns_empty(self):
        # REQ-SA-27.3: missing source falls back to ``{}`` so the LLM
        # regenerates with feedback alone.
        db, project = _make_past_phase_session(
            user_id=92,
            project_id=7,
            target_phase="requerimientos",
            current_phase="propuesta",
            elicitation_resumen=None,
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="modify",
            feedback="empezar de cero",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {}

    def test_modify_past_refinamiento_snapshots_attachments(self):
        # REQ-SA-27.2: latest assistant Message.attachments becomes the snapshot.
        attachments = [
            {
                "kind": "screenshot",
                "mime": "image/png",
                "url": "/api/chat/attachments/77?token=abc",
                "filename": "diagram.png",
                "source": "graph TD; A-->B",
            }
        ]
        db, project = _make_past_phase_session(
            user_id=93,
            project_id=7,
            target_phase="refinamiento",
            current_phase="revision",
            latest_attachments=attachments,
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="refinamiento",
            action="modify",
            feedback="incluir retries",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {"attachments": attachments}

    def test_modify_past_refinamiento_no_attachments_returns_empty(self):
        # No diagram ever streamed → ``{}`` fallback.
        db, project = _make_past_phase_session(
            user_id=94,
            project_id=7,
            target_phase="refinamiento",
            current_phase="revision",
            latest_attachments=None,
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="refinamiento",
            action="modify",
            feedback="definir mejor los nodos",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {}

    def test_modify_past_propuesta_still_snapshots_proposal(self):
        # Past-phase ``propuesta`` keeps the HU10 snapshot path intact.
        latest = MagicMock()
        latest.id = 7
        latest.content = {"componentes": ["API"]}
        latest.citations = [{"pattern_id": 3}]
        latest.iteration = 2
        db, project = _make_past_phase_session(
            user_id=95,
            project_id=7,
            target_phase="propuesta",
            current_phase="refinamiento",
            latest_proposal=latest,
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="propuesta",
            action="modify",
            feedback="agregar cache",
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {
            "content": {"componentes": ["API"]},
            "citations": [{"pattern_id": 3}],
            "iteration": 2,
        }
        # Dual-write to proposal_approvals MUST still fire (REQ-PA-HU10-1).
        pa = [a for a in db.adds if isinstance(a, phase_decisions.ProposalApproval)]
        assert len(pa) == 1
        assert pa[0].decision == "modified"

    def test_modify_past_revision_carries_tradeoffs(self):
        # Revision path is UI-edited (HU10 path); past-phase keeps that contract.
        db, project = _make_past_phase_session(
            user_id=96,
            project_id=7,
            target_phase="revision",
            current_phase="final",
        )
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="revision",
            action="modify",
            feedback="cambiar a event-driven",
            payload={
                "patron_elegido": "Event Sourcing",
                "ventajas": ["audit"],
                "desventajas": ["complexity"],
            },
        )
        approvals = [a for a in db.adds if isinstance(a, phase_decisions.Approval)]
        assert approvals[0].previous_output == {
            "patron_elegido": "Event Sourcing",
            "ventajas": ["audit"],
            "desventajas": ["complexity"],
        }

    def test_modify_past_phase_does_not_change_phase_ready(self):
        # ``modify`` is intentionally non-advancing — verify on past phase too.
        db, project = _make_past_phase_session(
            user_id=97,
            project_id=7,
            target_phase="requerimientos",
            current_phase="final",
            elicitation_resumen={"problema": "x"},
        )
        project.phase_ready = True
        phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase="requerimientos",
            action="modify",
            feedback="refinar",
        )
        assert project.phase_ready is True

    @pytest.mark.parametrize(
        "phase",
        ["requerimientos", "propuesta", "refinamiento", "revision"],
    )
    def test_modify_past_phase_parametrized_does_not_raise(self, phase):
        # Parametrized smoke: any past-phase modify succeeds regardless of
        # structured-source presence. Catches the gap HU10's _make_session
        # fixture hid by always pinning current_phase = phase.
        kwargs = dict(
            user_id=100,
            project_id=1,
            target_phase=phase,
            current_phase="final",
        )
        if phase == "propuesta":
            latest = MagicMock()
            latest.id = 1
            latest.content = {}
            latest.citations = []
            latest.iteration = 1
            kwargs["latest_proposal"] = latest
        elif phase == "refinamiento":
            kwargs["latest_attachments"] = []
        elif phase == "requerimientos":
            kwargs["elicitation_resumen"] = {"problema": "x"}
        db, project = _make_past_phase_session(**kwargs)
        result = phase_decisions.record_decision(
            db=db,
            project_id=project.id,
            phase=phase,
            action="modify",
            feedback="ajuste",
        )
        assert result.action == "modify"
        assert result.phase == phase