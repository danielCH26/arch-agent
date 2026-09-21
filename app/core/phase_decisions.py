"""Domain helper for per-phase approve / modify / reject decisions.

Issue #21 / HU10 — Staged Approvals. The single source of truth for the
canonical ``POST /api/projects/{id}/phase/{phase}/decision`` endpoint
declared in ``openspec/specs/staged-approvals/spec.md`` (REQ-SA-13).

Responsibilities:
- Validate the (phase, action) tuple against ``AVAILABLE_PHASES``.
- Enforce the 60-second idempotency window (REQ-SA-10) and return a
  ``DecisionConflict`` for any different-action decision inside the
  window (REQ-SA-9, 409 mapping happens at the HTTP edge).
- Persist the row in ``approvals`` with ``previous_output`` JSONB populated
  from the phase-specific prior content (REQ-SA-3, REQ-SA-16).
- Dual-write to ``proposal_approvals`` for ``phase == "propuesta"``
  (REQ-SA-17 / REQ-PA-HU10-1) so the F08 reader paths keep working.
- Update ``Project.phase_ready`` per the decision semantics and, on
  ``approve`` for ``final``, signal the caller that the project is done
  (``next_phase is None`` — REQ-SA-15).

The helper is pure: it does NOT open its own session, so the FastAPI route
keeps ownership of the transaction lifecycle and tests can use SQLite
in-memory (see ``tests/core/test_phase_decisions.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.message_store import ensure_user_session
from app.models import Approval, InteractionLog, Proposal, ProposalApproval
from app.models.project import Project
from app.models.session import UserSession


# ---------------------------------------------------------------------------
# Phase taxonomy (REQ-SA-4) — single source of truth.
# Re-exported from this module so the route layer and the tests agree on the
# canonical 5-phase list. ``app/api/projects.py`` keeps a parallel
# ``AVAILABLE_PHASES`` for backwards-compat; new code MUST use this one.
# ---------------------------------------------------------------------------

AVAILABLE_PHASES = [
    "requerimientos",
    "propuesta",
    "refinamiento",
    "revision",
    "final",
]

# Idempotency window per REQ-SA-10.
IDEMPOTENCY_WINDOW_SECONDS = 60

# Imperative body verb → past-participle DB value (matches the F05
# ``DECISION_TO_DB`` mapping in ``app/api/elicitation.py`` so existing
# readers see consistent values).
DECISION_TO_DB = {
    "approve": "approved",
    "modify": "modified",
    "reject": "rejected",
}

VALID_ACTIONS = frozenset(DECISION_TO_DB.keys())


# ---------------------------------------------------------------------------
# Result / exception types (route layer translates to HTTP responses).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseDecisionResult:
    """Successful outcome of ``record_decision``.

    Attributes mirror the ``DecisionResponse`` shape documented in
    ``design.md §D.1`` so the route can return it directly.
    """

    decision_id: int
    project_id: int
    phase: str
    action: str
    next_phase: Optional[str]
    decided_at: datetime
    idempotent: bool = False


class PhaseDecisionError(Exception):
    """Base for domain-level errors that map to HTTP exceptions at the edge."""


class ProjectNotFound(PhaseDecisionError):
    def __init__(self, project_id: int) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id


class InvalidPhase(PhaseDecisionError):
    def __init__(self, phase: str) -> None:
        super().__init__(f"phase {phase!r} is not in AVAILABLE_PHASES")
        self.phase = phase


class InvalidAction(PhaseDecisionError):
    def __init__(self, action: str) -> None:
        super().__init__(
            f"action {action!r} is not one of {sorted(VALID_ACTIONS)}"
        )
        self.action = action


class ModifyFeedbackRequired(PhaseDecisionError):
    def __init__(self) -> None:
        super().__init__("Modify requires non-empty feedback")


class DecisionConflict(PhaseDecisionError):
    """Raised when a different-action decision already exists in the window.

    Maps to HTTP 409 with body ``{current_decision, decided_at}`` per
    REQ-SA-9 / REQ-SA-15.
    """

    def __init__(
        self,
        current_decision: str,
        decided_at: datetime,
        phase: str,
    ) -> None:
        super().__init__(
            f"phase {phase!r} already decided as {current_decision!r} "
            f"at {decided_at.isoformat()}"
        )
        self.current_decision = current_decision
        self.decided_at = decided_at
        self.phase = phase


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_decision(
    db: Session,
    project_id: int,
    phase: str,
    action: str,
    feedback: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> PhaseDecisionResult:
    """Persist a per-phase approve / modify / reject decision.

    See module docstring for the full contract. This function owns:
    - idempotency check (SELECT last decision in window, raise on conflict,
      return original on identical action).
    - ``approvals`` INSERT with ``previous_output`` populated from
      phase-specific prior content.
    - ``proposal_approvals`` dual-write for ``phase == "propuesta"`` if a
      proposal row exists.
    - ``interaction_logs`` audit row.
    - ``Project.phase_ready`` update.

    Transaction handling is the caller's responsibility: ``db`` is expected
    to be an open ``Session`` that the caller will ``commit()`` (or
    ``rollback()``) after this call returns. Tests commit/rollback
    explicitly so failure cases stay isolated.
    """
    # --- Validation ---------------------------------------------------------
    if phase not in AVAILABLE_PHASES:
        raise InvalidPhase(phase)
    if action not in VALID_ACTIONS:
        raise InvalidAction(action)
    if action == "modify" and not (feedback and feedback.strip()):
        raise ModifyFeedbackRequired()

    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise ProjectNotFound(project_id)

    # Resolve the user's session row (F05 pattern — one session per user).
    # PR #78 review F1: a brand-new user (no UserSession row yet) whose very
    # first action is an approval used to raise a bare PhaseDecisionError
    # here, which the route mapped to an HTTP 500 — breaking the happy
    # path. Reuse the same lazy-upsert the chat persistence path relies on
    # (``app/core/message_store.ensure_user_session``) so the row is
    # created on demand instead of failing. At this point no writes are
    # pending on ``db``, so the helper's internal flush/rollback cannot
    # discard caller state.
    session_id = int(ensure_user_session(db, project.user_id))

    # --- Idempotency window (REQ-SA-9 / REQ-SA-10) --------------------------
    decision_db = DECISION_TO_DB[action]
    cutoff = datetime.utcnow() - timedelta(seconds=IDEMPOTENCY_WINDOW_SECONDS)
    existing = (
        db.query(Approval)
        .filter(
            Approval.session_id == session_id,
            Approval.phase == phase,
            Approval.created_at >= cutoff,
        )
        .order_by(Approval.created_at.desc())
        .first()
    )
    if existing is not None:
        if existing.decision == decision_db:
            # Identical action inside the window → 200 idempotent.
            return PhaseDecisionResult(
                decision_id=int(existing.id),
                project_id=project_id,
                phase=phase,
                action=action,
                next_phase=_compute_next_phase(project, phase, action),
                decided_at=existing.created_at,
                idempotent=True,
            )
        raise DecisionConflict(
            current_decision=existing.decision,
            decided_at=existing.created_at,
            phase=phase,
        )

    # --- Snapshot the prior content for ``previous_output`` -----------------
    previous_output = _build_previous_output(
        db, project_id=project_id, phase=phase, payload=payload or {}
    )

    # --- Insert canonical approval row --------------------------------------
    approval_row = Approval(
        session_id=session_id,
        phase=phase,
        decision=decision_db,
        feedback=feedback,
        previous_output=previous_output,
    )
    db.add(approval_row)
    db.flush()  # populate approval_row.id without committing

    # --- Dual-write for propuesta (REQ-SA-17 / REQ-PA-HU10-1) --------------
    # PR #78 review F2: the resolved proposal id also stamps the audit row
    # below so ``interaction_logs.proposal_id`` stays meaningful for
    # propuesta-phase decisions.
    propuesta_proposal_id = (
        _latest_proposal_id(db, project_id) if phase == "propuesta" else None
    )
    if phase == "propuesta" and propuesta_proposal_id is not None:
        db.add(
            ProposalApproval(
                proposal_id=propuesta_proposal_id,
                decision=decision_db,
                previous_output=previous_output,
            )
        )

    # --- Audit row ----------------------------------------------------------
    db.add(
        InteractionLog(
            session_id=session_id,
            project_id=project_id,
            proposal_id=propuesta_proposal_id,
            phase=phase,
            action_type=action,
            comment=feedback,
        )
    )

    # --- Update project.phase_ready -----------------------------------------
    if action == "approve":
        project.phase_ready = True
    elif action == "reject":
        # Reject does NOT advance the phase (REQ-SA-1.2 keeps current_phase
        # pinned) but resets phase_ready so the user must earn it again.
        project.phase_ready = False
    # modify leaves phase_ready alone (the user is still iterating).

    db.flush()
    decided_at = approval_row.created_at or datetime.utcnow()

    return PhaseDecisionResult(
        decision_id=int(approval_row.id),
        project_id=project_id,
        phase=phase,
        action=action,
        next_phase=_compute_next_phase(project, phase, action),
        decided_at=decided_at,
        idempotent=False,
    )


def get_latest_decision(
    db: Session,
    project_id: int,
    phase: str,
    within_seconds: int = IDEMPOTENCY_WINDOW_SECONDS,
) -> Optional[Approval]:
    """Return the most recent decision for ``(project_id, phase)`` inside
    the window. ``None`` if there is no decision in the window.

    Used by the HTTP route to enrich 409 responses with
    ``{current_decision, decided_at}`` without re-running the conflict
    check.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        return None
    session_row = (
        db.query(UserSession).filter(UserSession.user_id == project.user_id).first()
    )
    if session_row is None:
        return None
    cutoff = datetime.utcnow() - timedelta(seconds=within_seconds)
    return (
        db.query(Approval)
        .filter(
            Approval.session_id == int(session_row.id),
            Approval.phase == phase,
            Approval.created_at >= cutoff,
        )
        .order_by(Approval.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_previous_output(
    db: Session,
    *,
    project_id: int,
    phase: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return the JSONB snapshot that goes into ``approvals.previous_output``.

    Per ADR-014 §4 the shape differs per phase:
    - ``requerimientos``: ``{resumen: ...}`` from the elicitation state.
    - ``propuesta``: ``{content, citations}`` from the latest ``Proposal``.
    - ``refinamiento``: ``{mermaid_source, attachment_id}`` from chat state.
    - ``revision``: ``{patron_elegido, ventajas, desventajas}`` from the
      caller payload (UI-edited).
    - ``final``: ``{}`` (no meaningful prior content).

    Unknown phases and missing sources fall back to an empty object — the
    column is ``NOT NULL DEFAULT '{}'`` so the DB will accept it.
    """
    if phase == "revision":
        # The frontend sends the edited trade-offs in the payload.
        return {
            "patron_elegido": payload.get("patron_elegido", ""),
            "ventajas": list(payload.get("ventajas") or []),
            "desventajas": list(payload.get("desventajas") or []),
        }

    if phase == "propuesta":
        latest = _latest_proposal(db, project_id)
        if latest is None:
            return {}
        return {
            "content": latest.content,
            "citations": list(latest.citations or []),
            "iteration": int(latest.iteration),
        }

    # For other phases we don't have a structured source-of-truth for
    # "the prior content" yet (the LLM streams it into the chat buffer,
    # not into a JSONB column). Fall back to an empty snapshot so the
    # CHECK + NOT NULL constraints are satisfied; the column becomes useful
    # once F11/F12 engram_state lands per-phase structures.
    return {}


def _latest_proposal_id(db: Session, project_id: int) -> Optional[int]:
    """Return the most recent proposal id for the project, if any.

    Used by the dual-write to find the right ``proposal_approvals``
    foreign key when phase=propuesta.
    """
    latest = _latest_proposal(db, project_id)
    return int(latest.id) if latest is not None else None


def _latest_proposal(db: Session, project_id: int) -> Optional[Proposal]:
    return (
        db.query(Proposal)
        .filter(Proposal.project_id == project_id)
        .order_by(Proposal.iteration.desc())
        .first()
    )


def _compute_next_phase(
    project: Project, phase: str, action: str
) -> Optional[str]:
    """Return the next phase the project would land on after ``/advance``.

    Per REQ-SA-15.1: ``next_phase is None`` when ``phase == "final"`` AND
    ``action == "approve"`` (project archived). Reject on any phase keeps
    the user pinned (REQ-SA-1.2).

    The route does NOT advance here — it just signals the value to the
    frontend so it can show "Avanzar a X" hints. Advancement is owned by
    ``POST /api/projects/{id}/advance``.
    """
    if action != "approve":
        return None
    if phase == "final":
        return None
    try:
        idx = AVAILABLE_PHASES.index(phase)
    except ValueError:
        return None
    if idx + 1 >= len(AVAILABLE_PHASES):
        return None
    return AVAILABLE_PHASES[idx + 1]