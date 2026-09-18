"""Domain helper for per-phase approve / modify / reject decisions.

Issue #21 / HU10 — Staged Approvals. The single source of truth for the
canonical ``POST /api/projects/{id}/phase/{phase}/decision`` endpoint
declared in ``openspec/specs/staged-approvals/spec.md`` (REQ-SA-13).

Issue #22 / HU11 — Surgical Adjustment. Extends ``_build_previous_output``
(REQ-SA-27) so every phase has a non-empty snapshot when its structured
source-of-truth exists (was previously ``{}`` for ``requerimientos`` and
``refinamiento``).

Responsibilities:
- Validate the (phase, action) tuple against ``AVAILABLE_PHASES``.
- Enforce the 60-second idempotency window (REQ-SA-10) and return a
  ``DecisionConflict`` for any different-action decision inside the
  window (REQ-SA-9, 409 mapping happens at the HTTP edge).
- Persist the row in ``approvals`` with ``previous_output`` JSONB populated
  from the phase-specific prior content (REQ-SA-3, REQ-SA-16, REQ-SA-27).
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

from app.models import Approval, InteractionLog, Proposal, ProposalApproval
from app.models.message import Message
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
    session_row = (
        db.query(UserSession).filter(UserSession.user_id == project.user_id).first()
    )
    if session_row is None:
        # A project without a session is an inconsistent state; surface as
        # a generic 500-class error so the caller can map it appropriately.
        raise PhaseDecisionError(
            f"user {project.user_id} has no active session for project {project_id}"
        )
    session_id = int(session_row.id)

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
    if phase == "propuesta":
        proposal_id = _latest_proposal_id(db, project_id)
        if proposal_id is not None:
            db.add(
                ProposalApproval(
                    proposal_id=proposal_id,
                    decision=decision_db,
                    previous_output=previous_output,
                )
            )

    # --- Audit row ----------------------------------------------------------
    db.add(
        InteractionLog(
            session_id=session_id,
            project_id=project_id,
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

    if phase == "requerimientos":
        # REQ-SA-27 (HU11): F05 streams the elicitation summary into
        # ``session.engram_state[<project_id>]["requerimientos"]["resumen"]``.
        # Snapshot that summary here so a Modify on a past ``requerimientos``
        # phase carries the user's prior context into the LLM re-prompt.
        resumen = _load_elicitation_resumen(db, project_id)
        return {"resumen": resumen} if resumen is not None else {}

    if phase == "refinamiento":
        # REQ-SA-27 (HU11): F12/F13 stream the diagram + attachments into
        # ``messages.attachments`` (Mermaid source lives there). Snapshot the
        # most recent assistant message that carried attachments so the LLM
        # can reference the previous diagrama previo in the re-prompt.
        attachments = _latest_assistant_attachments(db, project_id)
        return {"attachments": attachments} if attachments else {}

    # ``final`` and any unknown phase: no meaningful prior content.
    # Fall back to an empty snapshot so the CHECK + NOT NULL constraints
    # are satisfied and the LLM regenerates with feedback alone.
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


def _load_elicitation_resumen(db: Session, project_id: int) -> Optional[dict]:
    """Return the elicitation summary JSON from ``sessions.engram_state``.

    HU11 REQ-SA-27. The key path is
    ``engram_state[<project_id>]["requerimientos"]["resumen"]`` — same shape
    F05 already produces via ``app.api.elicitation._phase_data_from_engram``.
    Returns ``None`` when the session row is missing, ``engram_state`` is
    null, or the per-project / per-phase keys are absent (e.g. a prior
    ``reject`` wiped state). ``_build_previous_output`` translates the
    ``None`` into ``{}`` so the LLM still regenerates with feedback alone.
    """
    # Per project.user_id (one UserSession per user per the F05 design);
    # if there is no session row yet we have nothing to snapshot.
    project = db.query(Project).filter(Project.id == project_id).first()
    if project is None:
        return None
    session_row = (
        db.query(UserSession)
        .filter(UserSession.user_id == project.user_id)
        .first()
    )
    if session_row is None:
        return None
    engram_state = session_row.engram_state or {}
    # Per-project scoping matches the F05 ``_phase_data_from_engram`` helper.
    project_state = engram_state.get(str(project_id)) or {}
    phase_data = project_state.get("requerimientos") or {}
    resumen = phase_data.get("resumen")
    return resumen if isinstance(resumen, dict) else None


def _latest_assistant_attachments(
    db: Session, project_id: int
) -> list[dict]:
    """Return the most recent assistant message's ``attachments`` list.

    HU11 REQ-SA-27 / SCN-SA-27.2. The Mermaid source lives in
    ``messages.attachments`` (F13 typed-attachments); we pick the newest
    assistant row that actually carries attachments and return them as-is.
    Returns ``[]`` when no such row exists (the caller falls back to
    ``{}``).
    """
    row = (
        db.query(Message)
        .filter(
            Message.project_id == project_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if row is None:
        return []
    raw = row.attachments
    if not raw:
        return []
    return list(raw) if isinstance(raw, list) else []


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