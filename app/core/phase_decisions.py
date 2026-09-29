"""HU10 v2 phase-decision domain helper (ADR-015, REQ-SA-27..36).

Closes PR #78 blockers + important findings:
    * REQ-SA-27: per-project filter on ``(project_id, phase)`` — no more
      cross-project contamination via the single-user ``UserSession``.
    * REQ-SA-28: ``record_decision`` rejects ``phase != project.current_phase``
      with a typed 409 carrying ``{current_phase}`` so the frontend can
      show a useful error.
    * REQ-SA-30: idempotency key =
      ``SHA256(canonical_json({action, payload, feedback}))[:32]``.
      Identical retries within 60 s return the same ``decision_id`` with
      ``idempotent=True``; different-action retries are accepted (the
      v1 blanket 60s window is gone).
    * REQ-SA-31: serialise concurrent decisions via ``SELECT ... FOR UPDATE``
      on the ``projects`` row. The lock is held until the caller commits
      (the helper itself does not commit — the caller owns the tx).
    * REQ-SA-34: typed ``DecisionConflict`` exception carrying
      ``{current_decision, decided_at, current_phase}`` — never ``str(exc)``
      leaks to clients.

The helper is intentionally split from ``app/core/session_store.py``
(which already centralises the ``approvals`` INSERT via
``record_approval_decision``): the session_store helper handles the row
INSERT in a uniform way across F05 / F08 / HU10; this module adds the
HU10-specific v2 contract on top.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.session_store import record_approval_decision
from app.models.approval import Approval
from app.models.project import Project

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AVAILABLE_PHASES: tuple[str, ...] = (
    "requerimientos",
    "propuesta",
    "refinamiento",
    "revision",
    "final",
)
"""REQ-SA-4: exactly five phases. ``final`` is a fifth phase for the
binary sign-off (REQ-SA-8)."""

VALID_ACTIONS: tuple[str, ...] = ("approve", "modify", "reject")

# Idempotency window (REQ-SA-30). Identical retries inside this window
# return the original decision with ``idempotent=True``.
IDEMPOTENCY_WINDOW_SECONDS = 60

# Phase ownership (REQ-SA-36). F05 owns ``requerimientos`` and writes its
# own approval row directly via ``app/api/elicitation.py``. HU10 v2 owns
# the remaining four phases.
HU10_OWNED_PHASES: frozenset[str] = frozenset(
    {"propuesta", "refinamiento", "revision", "final"}
)
F05_OWNED_PHASES: frozenset[str] = frozenset({"requerimientos"})


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class PhaseDecisionError(ValueError):
    """Base class for HU10 v2 phase-decision errors."""

    http_status = 400


class InvalidPhaseError(PhaseDecisionError):
    """REQ-SA-4: phase is not in AVAILABLE_PHASES."""

    http_status = 422


class InvalidActionError(PhaseDecisionError):
    """REQ-SA-14: action is not in VALID_ACTIONS, or modify missing feedback."""

    http_status = 422


class PhaseMismatchError(PhaseDecisionError):
    """REQ-SA-28: requested ``phase`` does not equal ``project.current_phase``.

    The endpoint serialises this into a 409 with the body shape::

        {"detail": {"error": "phase_mismatch",
                    "current_phase": "<str>",
                    "requested_phase": "<str>"}}
    """

    http_status = 409

    def __init__(self, current_phase: str, requested_phase: str) -> None:
        super().__init__(
            f"requested_phase={requested_phase!r} != current_phase={current_phase!r}"
        )
        self.current_phase = current_phase
        self.requested_phase = requested_phase


@dataclass
class DecisionConflict:
    """REQ-SA-34: typed body for 409 conflicts.

    Returned by ``record_decision`` when an identical retry is NOT in
    scope (i.e. the recent decision was a different action/payload), so
    the caller raises HTTP 409 with this body verbatim — never
    ``str(exc)``.
    """

    current_decision: str
    decided_at: datetime
    current_phase: str
    decision_id: int

    def to_detail(self) -> dict[str, Any]:
        """FastAPI ``HTTPException(detail=...)`` payload."""
        return {
            "error": "decision_conflict",
            "current_decision": self.current_decision,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "current_phase": self.current_phase,
            "decision_id": self.decision_id,
        }


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class PhaseDecisionResult:
    """Outcome of ``record_decision``.

    Attributes:
        approval: the inserted (or matched-on-retry) ``Approval`` row.
        idempotent: True if this call returned the same row that was
            already on file (identical retry inside the 60s window).
        phase: the phase this result is for.
        next_phase: phase the project will move into next, or ``None`` if
            the user is on ``final`` (REQ-SA-15.1).
        phase_ready: ``True`` when the decision was an approve.
    """

    approval: Approval
    idempotent: bool
    phase: str
    next_phase: Optional[str]
    phase_ready: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_phase(current: str) -> Optional[str]:
    """Return the phase after ``current`` in AVAILABLE_PHASES, or None at final."""
    if current not in AVAILABLE_PHASES:
        return None
    idx = AVAILABLE_PHASES.index(current)
    if idx == len(AVAILABLE_PHASES) - 1:
        return None
    return AVAILABLE_PHASES[idx + 1]


def _canonical_payload_hash(
    action: str,
    payload: Optional[dict],
    feedback: Optional[str] = None,
) -> str:
    """REQ-SA-30: SHA256 hex truncated to 32 chars of
    ``canonical_json({action, payload, feedback})``.

    The action is included so ``modify`` + ``approve`` are different keys
    — this is the rule that unblocks legitimate ``modify -> approve``
    flows inside the 60s window. The normalized ``feedback`` (``None`` and
    whitespace-only collapse to ``""``) is included so two ``modify``
    submissions with different feedback text are never collapsed into one
    idempotent key — the real frontend sends ``feedback`` and no
    ``payload``, so dropping it from the key silently returned the
    original decision for corrected feedback.

    Pure and deterministic: same inputs always produce the same key.
    """
    blob = json.dumps(
        {
            "action": action,
            "payload": payload or {},
            "feedback": (feedback or "").strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Core entrypoint
# ---------------------------------------------------------------------------


def record_decision(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    phase: str,
    action: Literal["approve", "modify", "reject"],
    feedback: Optional[str] = None,
    payload: Optional[dict] = None,
    idempotency_key: Optional[str] = None,
    previous_output: Optional[dict] = None,
    attachment_id: Optional[str] = None,
) -> PhaseDecisionResult:
    """Record a phase decision for ``(project_id, phase)``.

    Behaviour:

      1. Validate ``phase`` and ``action`` (``modify`` requires
         ``feedback``); raise ``InvalidPhaseError`` / ``InvalidActionError``.
      2. ``SELECT ... FOR UPDATE`` on the ``projects`` row (REQ-SA-31).
         A concurrent caller blocks here until the holder commits.
      3. Validate ``phase == project.current_phase``; raise
         ``PhaseMismatchError`` (mapped to 409) otherwise (REQ-SA-28).
   4. Derive the idempotency key from ``(action, payload, feedback)``
      if the caller did not pass one explicitly (REQ-SA-30).
      5. Look up the most recent ``Approval`` for
         ``(project_id, phase, created_at >= now-60s)``. If its
         ``payload_hash`` matches the new key, return it with
         ``idempotent=True`` (REQ-SA-30.1). A different action/payload
         hash in the window does NOT short-circuit — it accepts the new
         decision (REQ-SA-30.2).
      6. Insert via ``record_approval_decision`` (the F05/F08 shared
         writer) carrying ``project_id``, ``payload``, ``payload_hash``,
         and the optional ``previous_output`` snapshot.
      7. Update ``projects.phase_ready``: True on approve, False on
         reject/modify.
      8. Return ``PhaseDecisionResult``. The caller commits the
         transaction.

    The helper does NOT commit — the caller owns the tx so any
    surrounding work rolls back together (mirrors the contract from
    ``record_approval_decision`` in ``session_store.py``).
    """
    # ---- 1. Input validation ----
    if phase not in AVAILABLE_PHASES:
        raise InvalidPhaseError(f"phase {phase!r} is not in AVAILABLE_PHASES")
    if action not in VALID_ACTIONS:
        raise InvalidActionError(
            f"action {action!r} is not in VALID_ACTIONS={VALID_ACTIONS}"
        )
    if action == "modify" and not (feedback and feedback.strip()):
        raise InvalidActionError("'modify' requires non-empty feedback")

    # ---- 2. Project lookup with FOR UPDATE (REQ-SA-31) ----
    project = db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    ).scalar_one_or_none()
    if project is None:
        raise PhaseDecisionError(f"project_id={project_id} not found")

    # ---- 3. Phase == current_phase gate (REQ-SA-28) ----
    if phase != project.current_phase:
        raise PhaseMismatchError(
            current_phase=project.current_phase or "",
            requested_phase=phase,
        )

    # ---- 4. Idempotency key derivation (REQ-SA-30) ----
    key = idempotency_key or _canonical_payload_hash(action, payload, feedback)

    # ---- 5. Idempotent retry check (REQ-SA-30.1) ----
    recent = db.execute(
        select(Approval)
        .where(
            Approval.project_id == project_id,
            Approval.phase == phase,
            Approval.created_at
            >= datetime.utcnow() - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS),
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if recent is not None and recent.payload_hash == key:
        # Identical retry — return original row, idempotent=True.
        # Do NOT re-update projects.phase_ready (no-op).
        logger.info(
            "record_decision: idempotent retry project_id=%s phase=%s decision_id=%s",
            project_id,
            phase,
            recent.id,
        )
        return PhaseDecisionResult(
            approval=recent,
            idempotent=True,
            phase=phase,
            next_phase=_next_phase(phase),
            phase_ready=bool(project.phase_ready),
        )

    # ---- 6. Insert via the shared writer (REQ-SA-17 dual-write stays in the
    # endpoint layer; this helper covers the canonical approvals row only). ----
    approval = record_approval_decision(
        db,
        user_id=user_id,
        phase=phase,
        decision=action,
        feedback=feedback,
        project_id=project_id,
        attachment_id=attachment_id,
    )
    # Add the v2-specific fields the shared writer does not know about.
    approval.payload = payload
    approval.payload_hash = key
    if previous_output is not None:
        approval.previous_output = previous_output
    db.flush()

    # ---- 7. Update projects.phase_ready ----
    if action == "approve":
        project.phase_ready = True
    else:
        # modify + reject both flip phase_ready to False; the user must
        # re-trigger /advance after a fresh approval.
        project.phase_ready = False

    return PhaseDecisionResult(
        approval=approval,
        idempotent=False,
        phase=phase,
        next_phase=_next_phase(phase),
        phase_ready=bool(project.phase_ready),
    )


# ---------------------------------------------------------------------------
# Pending decision read path (REQ-SA-12, REQ-SA-26)
# ---------------------------------------------------------------------------


@dataclass
class PendingDecision:
    """Single pending-decision view used by GET /api/projects/{id}/phases.

    ``since`` is the most recent decision's created_at (UTC). ``None``
    when no decision is on file for the phase.
    """

    phase: str
    since: Optional[datetime]
    last_decision: Optional[str]
    last_decided_at: Optional[datetime]


def get_pending_decision(
    db: Session, *, project_id: int
) -> Optional[PendingDecision]:
    """Return the latest decision for ``(project_id, current_phase)``,
    or ``None`` when no decision is on file for the current phase.

    This is the canonical helper for ``GET /api/projects/{id}/phases``
    (REQ-SA-12). The frontend ``approvalsStore`` reads the top-level
    ``pending_decision`` from the response and mounts
    ``<PhaseActions>`` if it is non-null (REQ-SA-26.1).
    """
    project = db.execute(
        select(Project).where(Project.id == project_id)
    ).scalar_one_or_none()
    if project is None or not project.current_phase:
        return None

    recent = db.execute(
        select(Approval)
        .where(
            Approval.project_id == project_id,
            Approval.phase == project.current_phase,
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if recent is None:
        return None

    return PendingDecision(
        phase=project.current_phase,
        since=recent.created_at,
        last_decision=recent.decision,
        last_decided_at=recent.created_at,
    )


# ---------------------------------------------------------------------------
# /advance single-owner enforcement (REQ-SA-36)
# ---------------------------------------------------------------------------


class PhaseNotApprovedError(PhaseDecisionError):
    """REQ-SA-36: HU10-owned phase has no HU10 approval row before /advance.

    Maps to HTTP 409 with detail ``{"error": "phase_not_approved", "phase": ...}``.
    """

    http_status = 409

    def __init__(self, phase: str) -> None:
        super().__init__(f"phase {phase!r} has no HU10 approval row")
        self.phase = phase


def assert_hu10_approval_for_current_phase(
    db: Session, *, project_id: int
) -> None:
    """REQ-SA-36: if the project's current phase is HU10-owned, ensure
    a recent ``approved`` decision exists before /advance can flip the
    phase.

    Raises ``PhaseNotApprovedError`` (mapped to 409) when the gate is
    missing. F05-owned phases (``requerimientos``) are skipped — F05 is
    the canonical owner and writes its own approval row via
    ``app/api/elicitation.py``.
    """
    project = db.execute(
        select(Project).where(Project.id == project_id)
    ).scalar_one_or_none()
    if project is None or not project.current_phase:
        return  # endpoint layer will 404

    if project.current_phase not in HU10_OWNED_PHASES:
        return  # F05 owns this phase; no HU10 gate required

    approved = db.execute(
        select(Approval)
        .where(
            Approval.project_id == project_id,
            Approval.phase == project.current_phase,
            Approval.decision == "approved",
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if approved is None:
        raise PhaseNotApprovedError(project.current_phase)