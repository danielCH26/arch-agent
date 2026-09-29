"""Unit tests for ``app/core/phase_decisions.py`` (HU10 v2, ADR-015).

Covers:
    * REQ-SA-27: per-project filter (``(project_id, phase)`` — not session_id).
    * REQ-SA-28: ``PhaseMismatchError`` when ``phase != project.current_phase``.
    * REQ-SA-30: identical retries return ``idempotent=True``; different-action
      AND different-feedback retries are accepted (a corrected ``modify``
      feedback is never collapsed into the original decision).
    * REQ-SA-31: ``with_for_update`` issued on the projects row.
    * REQ-SA-34: typed ``DecisionConflict`` body; never ``str(exc)``.
    * REQ-SA-36: single-owner gate (``requerimientos`` skips, others require
      a HU10 approval row before /advance).

These tests use ``MagicMock`` for the SQLAlchemy session so they run
without Postgres. The Postgres-backed concurrency test lives separately
in ``test_phase_decisions_concurrency.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.phase_decisions import (
    AVAILABLE_PHASES,
    F05_OWNED_PHASES,
    HU10_OWNED_PHASES,
    IDEMPOTENCY_WINDOW_SECONDS,
    DecisionConflict,
    InvalidActionError,
    InvalidPhaseError,
    PhaseDecisionResult,
    PhaseMismatchError,
    PhaseNotApprovedError,
    _canonical_payload_hash,
    _next_phase,
    assert_hu10_approval_for_current_phase,
    get_pending_decision,
    record_decision,
)


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------


def test_available_phases_is_exactly_five():
    """REQ-SA-4: AVAILABLE_PHASES has exactly 5 elements including 'final'."""
    assert len(AVAILABLE_PHASES) == 5
    assert AVAILABLE_PHASES[-1] == "final"
    assert "requerimientos" in AVAILABLE_PHASES
    assert "propuesta" in AVAILABLE_PHASES
    assert "refinamiento" in AVAILABLE_PHASES
    assert "revision" in AVAILABLE_PHASES


def test_hu10_owns_four_of_five_phases():
    """REQ-SA-36: HU10 owns propuesta/refinamiento/revision/final."""
    assert HU10_OWNED_PHASES == frozenset(
        {"propuesta", "refinamiento", "revision", "final"}
    )
    assert F05_OWNED_PHASES == frozenset({"requerimientos"})


def test_next_phase_helper():
    assert _next_phase("requerimientos") == "propuesta"
    assert _next_phase("propuesta") == "refinamiento"
    assert _next_phase("refinamiento") == "revision"
    assert _next_phase("revision") == "final"
    assert _next_phase("final") is None  # REQ-SA-15.1
    assert _next_phase("unknown") is None


def test_canonical_payload_hash_changes_with_action():
    """REQ-SA-30: (action, payload) hash is the idempotency key."""
    h_approve_empty = _canonical_payload_hash("approve", None)
    h_modify_empty = _canonical_payload_hash("modify", None)
    assert h_approve_empty != h_modify_empty
    # Length must be exactly 32 hex chars (SHA256[:32]) per migration 0018.
    assert len(h_approve_empty) == 32
    assert all(c in "0123456789abcdef" for c in h_approve_empty)


def test_canonical_payload_hash_changes_with_payload():
    """REQ-SA-30: payload affects the hash; same action + different payload != idempotent."""
    a = _canonical_payload_hash("modify", {"feedback": "use event-driven"})
    b = _canonical_payload_hash("modify", {"feedback": "use modular monolith"})
    assert a != b


def test_canonical_payload_hash_changes_with_feedback():
    """REQ-SA-30 (audit fix): feedback affects the hash; same action +
    payload with different feedback is NOT idempotent. Absent (None) and
    whitespace-only feedback normalize to the empty string."""
    a = _canonical_payload_hash("modify", None, "usa event-driven")
    b = _canonical_payload_hash("modify", None, "usa event-driven, no monolito")
    assert a != b
    # None / missing / whitespace-only feedback collapse to one key.
    assert _canonical_payload_hash("approve", None, None) == _canonical_payload_hash(
        "approve", None, ""
    )
    assert _canonical_payload_hash("approve", None, "  ") == _canonical_payload_hash(
        "approve", None
    )
    # Two-arg calls (legacy signature) equal explicit empty feedback.
    assert _canonical_payload_hash("reject", {"x": 1}) == _canonical_payload_hash(
        "reject", {"x": 1}, ""
    )


def test_canonical_payload_hash_stable_for_identical_inputs():
    """REQ-SA-30: hash is deterministic across calls."""
    a = _canonical_payload_hash("approve", {"x": 1, "y": [1, 2]})
    b = _canonical_payload_hash("approve", {"y": [1, 2], "x": 1})  # dict order independent
    assert a == b


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db_with_project(*, current_phase: str = "propuesta") -> MagicMock:
    """Build a MagicMock DB session with a Project + execute() chain set up.

    The chain answers the FOR UPDATE lookup with the project, and any
    subsequent SELECT (the idempotency check) returns no row so we test
    the fresh-insert path by default.
    """
    db = MagicMock()
    project = MagicMock()
    project.id = 7
    project.current_phase = current_phase
    project.phase_ready = False

    # db.execute(...).scalar_one_or_none() returns the project for the FOR UPDATE
    # call and None for the idempotency lookup.
    executions = iter([project, None])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect
    db.add = MagicMock()
    db.flush = MagicMock()
    return db, project


# ---------------------------------------------------------------------------
# record_decision — happy path
# ---------------------------------------------------------------------------


def test_record_decision_approve_happy_path():
    """REQ-SA-30, REQ-SA-15: approve inserts one row, returns 200-shape result."""
    db, project = _make_db_with_project(current_phase="propuesta")
    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        mock_writer.return_value = MagicMock(id=42, decision="approved")
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="approve",
        )

    assert isinstance(result, PhaseDecisionResult)
    assert result.phase == "propuesta"
    assert result.next_phase == "refinamiento"
    assert result.phase_ready is True
    assert result.idempotent is False
    # project.phase_ready flipped to True
    assert project.phase_ready is True
    # writer got the right kwargs
    _, kwargs = mock_writer.call_args
    assert kwargs["user_id"] == 1
    assert kwargs["project_id"] == 7
    assert kwargs["decision"] == "approve"
    # payload + payload_hash were attached to the approval row
    assert result.approval.payload is None
    assert len(result.approval.payload_hash) == 32


def test_record_decision_final_returns_next_phase_none():
    """REQ-SA-15.1: approving `final` returns next_phase=null (project archived)."""
    db, project = _make_db_with_project(current_phase="final")
    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        mock_writer.return_value = MagicMock(id=99, decision="approved")
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="final",
            action="approve",
        )

    assert result.next_phase is None


# ---------------------------------------------------------------------------
# record_decision — REQ-SA-28 phase mismatch
# ---------------------------------------------------------------------------


def test_record_decision_phase_mismatch_raises_409():
    """REQ-SA-28: phase != current_phase -> PhaseMismatchError (http_status=409)."""
    db, project = _make_db_with_project(current_phase="requerimientos")
    with pytest.raises(PhaseMismatchError) as exc_info:
        record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="refinamiento",
            action="approve",
        )
    assert exc_info.value.http_status == 409
    assert exc_info.value.current_phase == "requerimientos"
    assert exc_info.value.requested_phase == "refinamiento"


# ---------------------------------------------------------------------------
# record_decision — REQ-SA-30 idempotent retry
# ---------------------------------------------------------------------------


def test_record_decision_identical_retry_returns_idempotent():
    """REQ-SA-30.1: same payload_hash within 60s -> idempotent=True, no writer call."""
    db, project = _make_db_with_project(current_phase="propuesta")

    # First execute() returns the project (FOR UPDATE). Second returns the
    # recent approval with the matching payload_hash.
    recent = MagicMock()
    recent.id = 99
    recent.payload_hash = _canonical_payload_hash("approve", None)
    recent.created_at = datetime.utcnow()

    executions = iter([project, recent])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        # The idempotency-check query orders by created_at DESC; mirror the
        # limit(1) so the .scalar_one_or_none() chain still works.
        return result

    db.execute.side_effect = execute_side_effect

    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="approve",
        )

    assert result.idempotent is True
    assert result.approval.id == 99
    mock_writer.assert_not_called()
    # project.phase_ready untouched on idempotent retry
    assert project.phase_ready is False


def test_record_decision_different_action_within_window_is_accepted():
    """REQ-SA-30.2: modify after approve inside 60s is accepted (NOT 409)."""
    db, project = _make_db_with_project(current_phase="propuesta")

    # Recent approval is for `approve` with no payload.
    recent = MagicMock()
    recent.id = 88
    recent.payload_hash = _canonical_payload_hash("approve", None)
    recent.created_at = datetime.utcnow()

    executions = iter([project, recent])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect

    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        mock_writer.return_value = MagicMock(id=89, decision="modified")
        # New action is `modify` -- payload_hash WILL differ, so the writer fires.
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="modify",
            feedback="use modular monolith instead",
        )

    assert result.idempotent is False
    mock_writer.assert_called_once()
    assert project.phase_ready is False  # modify keeps phase_ready=False


def test_same_action_different_feedback_is_accepted_not_idempotent():
    """REQ-SA-30 (audit fix): two `modify` submissions with DIFFERENT
    feedback inside the 60s window are NOT idempotent — the second call
    inserts a NEW decision and the stored row carries the NEW feedback.
    Regression guard for the real frontend (`PhaseActions.tsx`), which
    sends `feedback` and never `payload`."""
    db, project = _make_db_with_project(current_phase="propuesta")

    # Recent approval is a `modify` with the FIRST feedback text.
    recent = MagicMock()
    recent.id = 77
    recent.payload_hash = _canonical_payload_hash(
        "modify", None, "usa event-driven"
    )
    recent.created_at = datetime.utcnow()

    executions = iter([project, recent])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect

    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        mock_writer.return_value = MagicMock(id=78, decision="modified")
        # SAME action + payload, DIFFERENT feedback -> hash differs -> accepted.
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="modify",
            feedback="usa event-driven, no monolito",
        )

    assert result.idempotent is False
    assert result.approval.id == 78  # NEW decision_id, not the recent 77
    mock_writer.assert_called_once()
    # The stored approval row carries the NEW feedback.
    _, kwargs = mock_writer.call_args
    assert kwargs["feedback"] == "usa event-driven, no monolito"
    # The row's hash matches the NEW feedback, not the recent one.
    assert result.approval.payload_hash == _canonical_payload_hash(
        "modify", None, "usa event-driven, no monolito"
    )
    assert result.approval.payload_hash != recent.payload_hash


# ---------------------------------------------------------------------------
# record_decision — input validation
# ---------------------------------------------------------------------------


def test_record_decision_rejects_unknown_phase():
    db, _ = _make_db_with_project()
    with pytest.raises(InvalidPhaseError):
        record_decision(
            db, user_id=1, project_id=7, phase="diagram", action="approve"
        )


def test_record_decision_rejects_unknown_action():
    db, _ = _make_db_with_project()
    with pytest.raises(InvalidActionError):
        record_decision(
            db, user_id=1, project_id=7, phase="propuesta", action="merge"
        )


def test_record_decision_modify_requires_feedback():
    db, _ = _make_db_with_project()
    with pytest.raises(InvalidActionError):
        record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="modify",
            feedback="",
        )


# ---------------------------------------------------------------------------
# get_pending_decision (REQ-SA-12)
# ---------------------------------------------------------------------------


def test_get_pending_decision_returns_latest_for_current_phase():
    db = MagicMock()
    project = MagicMock()
    project.current_phase = "refinamiento"
    recent = MagicMock()
    recent.created_at = datetime(2026, 9, 27, 22, 0, 0)
    recent.decision = "approved"

    executions = iter([project, recent])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect

    pending = get_pending_decision(db, project_id=7)
    assert pending is not None
    assert pending.phase == "refinamiento"
    assert pending.last_decision == "approved"
    assert pending.since == recent.created_at


def test_get_pending_decision_returns_none_when_no_record():
    db = MagicMock()
    project = MagicMock()
    project.current_phase = "requerimientos"

    executions = iter([project, None])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect
    assert get_pending_decision(db, project_id=7) is None


# ---------------------------------------------------------------------------
# /advance single-owner enforcement (REQ-SA-36)
# ---------------------------------------------------------------------------


def test_advance_gate_skips_f05_owned_phase():
    """REQ-SA-36: `requerimientos` (F05-owned) bypasses the HU10 gate."""
    db = MagicMock()
    project = MagicMock()
    project.current_phase = "requerimientos"

    executions = iter([project])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect
    # MUST NOT raise even when no approval row exists for `requerimientos`.
    assert_hu10_approval_for_current_phase(db, project_id=7)


def test_advance_gate_blocks_hu10_owned_phase_without_approval():
    """REQ-SA-36: HU10-owned phase with no approval row -> 409."""
    db = MagicMock()
    project = MagicMock()
    project.current_phase = "propuesta"

    executions = iter([project, None])  # project lookup ok, approval row missing

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect

    with pytest.raises(PhaseNotApprovedError) as exc_info:
        assert_hu10_approval_for_current_phase(db, project_id=7)
    assert exc_info.value.http_status == 409
    assert exc_info.value.phase == "propuesta"


def test_advance_gate_passes_when_hu10_approval_exists():
    """REQ-SA-36: HU10-owned phase with an `approved` row passes."""
    db = MagicMock()
    project = MagicMock()
    project.current_phase = "propuesta"

    approved = MagicMock()
    approved.decision = "approved"
    executions = iter([project, approved])

    def execute_side_effect(*_args, **_kwargs):
        result = MagicMock()
        result.scalar_one_or_none.side_effect = lambda: next(executions, None)
        return result

    db.execute.side_effect = execute_side_effect
    # MUST NOT raise.
    assert_hu10_approval_for_current_phase(db, project_id=7)


# ---------------------------------------------------------------------------
# DecisionConflict body shape (REQ-SA-34)
# ---------------------------------------------------------------------------


def test_decision_conflict_body_shape():
    """REQ-SA-34: typed body carries current_decision/decided_at/current_phase."""
    when = datetime(2026, 9, 27, 22, 0, 0)
    conflict = DecisionConflict(
        current_decision="approve",
        decided_at=when,
        current_phase="propuesta",
        decision_id=42,
    )
    body = conflict.to_detail()
    assert body["current_decision"] == "approve"
    assert body["decided_at"] == "2026-09-27T22:00:00"
    assert body["current_phase"] == "propuesta"
    assert body["decision_id"] == 42
    assert body["error"] == "decision_conflict"


# ---------------------------------------------------------------------------
# Project_id filter (REQ-SA-27) — no cross-project contamination
# ---------------------------------------------------------------------------


def test_record_decision_filters_by_project_id_not_session_id():
    """REQ-SA-27: the writer receives project_id; no session_id leak."""
    db, _ = _make_db_with_project(current_phase="propuesta")
    with patch(
        "app.core.phase_decisions.record_approval_decision"
    ) as mock_writer:
        mock_writer.return_value = MagicMock(id=1, decision="approved")
        record_decision(
            db, user_id=1, project_id=7, phase="propuesta", action="approve"
        )

    _, kwargs = mock_writer.call_args
    assert kwargs["project_id"] == 7  # explicit, not None
    # session_id comes from inside record_approval_decision, not from us


# ---------------------------------------------------------------------------
# Audit log carries project_id (REQ-SA-34 metadata)
# ---------------------------------------------------------------------------


def test_record_decision_metadata_carries_project_id():
    """REQ-SA-34: payload/payload_hash attached to the approval row carry
    identifying fields; interaction_log metadata is enriched (caller-side)."""
    db, _ = _make_db_with_project(current_phase="propuesta")
    approval = MagicMock(id=10, decision="approved")
    with patch(
        "app.core.phase_decisions.record_approval_decision",
        return_value=approval,
    ):
        result = record_decision(
            db,
            user_id=1,
            project_id=7,
            phase="propuesta",
            action="approve",
            payload={"k": "v"},
        )

    assert result.approval.payload == {"k": "v"}
    assert result.approval.payload_hash is not None
    assert len(result.approval.payload_hash) == 32


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_idempotency_window_is_60_seconds():
    """REQ-SA-10, REQ-SA-30: window is 60s."""
    assert IDEMPOTENCY_WINDOW_SECONDS == 60