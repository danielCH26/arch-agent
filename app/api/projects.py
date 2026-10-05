from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.dependencies import get_current_user
from app.auth.validators import ValidationError
from app.core.database import SessionLocal
from app.models.approval import Approval
from app.models.project import Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


# --- Pydantic models ----------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    current_phase: Optional[str]
    phase_ready: bool
    created_at: str

    class Config:
        from_attributes = True


class PendingDecisionOut(BaseModel):
    """REQ-SA-12, REQ-SA-26: lightweight pending-decision surface."""

    phase: str
    since: Optional[str]  # ISO-8601 UTC; null when no decision on file
    last_decision: Optional[str]
    last_decided_at: Optional[str]


class PhaseOut(BaseModel):
    """Legacy single-phase response (kept for backward compat with F05/F08 callers)."""

    current_phase: str
    phase_ready: bool
    available_phases: list[str]


class PhasesOut(BaseModel):
    """REQ-SA-12, REQ-SA-26: GET /api/projects/{id}/phases response.

    ``pending_decision`` is the canonical mount signal for ``<PhaseActions>``
    on the frontend (defense-in-depth with the SSE ``event: phase_locked``).
    """

    phases: list[dict]
    current_phase: str
    phase_ready: bool
    available_phases: list[str]
    pending_decision: Optional[PendingDecisionOut] = None


class PhaseAdvanceOut(BaseModel):
    current_phase: str
    phase_ready: bool
    message: str


class PhaseDecisionIn(BaseModel):
    """REQ-SA-14: POST .../phase/{phase}/decision body."""

    action: str  # 'approve' | 'modify' | 'reject'
    feedback: Optional[str] = None
    payload: Optional[dict] = None
    idempotency_key: Optional[str] = None
    previous_output: Optional[dict] = None  # REQ-SA-35: snapshot from prior phase


class PhaseDecisionOut(BaseModel):
    """REQ-SA-15: 200 response shape."""

    decision_id: int
    action: str
    phase: str
    project_id: int
    next_phase: Optional[str]
    decided_at: str
    idempotent: bool


# REQ-SA-4: exactly 5 phases. ``final`` is the new binary sign-off phase
# (REQ-SA-8: only Aprobar / Rechazar; no Modificar).
AVAILABLE_PHASES = [
    "requerimientos",
    "propuesta",
    "refinamiento",
    "revision",
    "final",
]
PHASE_LABELS = {
    "requerimientos": "Requerimientos",
    "propuesta": "Propuesta",
    "refinamiento": "Refinamiento",
    "revision": "Revisión",
    "final": "Cierre",
}


# --- Helpers (reuse from app.py) -----------------------------------------------

def _require_project(user_id: int, project_id: int) -> Project:
    """Load project and raise 403/404 if not found or not owned."""

    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            # Check if exists at all
            exists = db.query(Project).filter(Project.id == project_id).first()
            if exists:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")
        return project
    finally:
        db.close()


# --- Routes -------------------------------------------------------------------

@router.get("", response_model=list[ProjectOut])
async def list_projects(current_user: dict = Depends(get_current_user)):
    """List all projects for the authenticated user."""
    from sqlalchemy import desc

    db = SessionLocal()
    try:
        projects = db.query(Project).filter(
            Project.user_id == current_user["user_id"]
        ).order_by(desc(Project.created_at)).all()
        return [
            ProjectOut(
                id=p.id,
                name=p.name,
                description=p.description,
                current_phase=p.current_phase,
                phase_ready=p.phase_ready,
                created_at=p.created_at.isoformat() if p.created_at else "",
            )
            for p in projects
        ]
    finally:
        db.close()


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new project (phase: requerimientos)."""

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre del proyecto no puede estar vacío")

    db = SessionLocal()
    try:
        # Check duplicate
        existing = db.query(Project).filter(
            Project.user_id == current_user["user_id"],
            Project.name == name,
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya tienes un proyecto llamado '{name}'",
            )

        project = Project(
            user_id=current_user["user_id"],
            name=name,
            description=body.description,
            current_phase="requerimientos",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            current_phase=project.current_phase,
            phase_ready=project.phase_ready,
            created_at=project.created_at.isoformat() if project.created_at else "",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get a single project by ID."""
    project = _require_project(current_user["user_id"], project_id)
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        current_phase=project.current_phase,
        phase_ready=project.phase_ready,
        created_at=project.created_at.isoformat() if project.created_at else "",
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete a project."""
    project = _require_project(current_user["user_id"], project_id)

    db = SessionLocal()
    try:
        db.delete(project)
        db.commit()
    finally:
        db.close()


@router.get("/{project_id}/phase", response_model=PhaseOut)
async def get_phase(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Legacy single-phase response (backward compat). For new consumers,
    prefer GET /phases which includes ``pending_decision`` (REQ-SA-12)."""
    project = _require_project(current_user["user_id"], project_id)
    return PhaseOut(
        current_phase=project.current_phase or "requerimientos",
        phase_ready=project.phase_ready,
        available_phases=AVAILABLE_PHASES,
    )


# REQ-SA-12, REQ-SA-26: GET /api/projects/{id}/phases returns the canonical
# phase list + a top-level ``pending_decision`` so the frontend ``<ChatWindow>``
# can mount ``<PhaseActions>`` from this fetch path even when the SSE
# ``event: phase_locked`` is missed (defense-in-depth).
@router.get("/{project_id}/phases", response_model=PhasesOut)
async def get_phases(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """List all 5 phases + current/pending state (REQ-SA-4, REQ-SA-12)."""
    from app.core.phase_decisions import get_pending_decision

    _require_project(current_user["user_id"], project_id)

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

        pending = get_pending_decision(db, project_id=project_id)
        pending_out: Optional[PendingDecisionOut] = None
        if pending is not None:
            # Include explicit +00:00 suffix for JavaScript Date() parsing
            since_iso = pending.since.isoformat() if pending.since else None
            if since_iso and pending.since.tzinfo is None:
                since_iso = since_iso + "+00:00"
            pending_out = PendingDecisionOut(
                phase=pending.phase,
                since=since_iso,
                last_decision=pending.last_decision,
                last_decided_at=(
                    pending.last_decided_at.isoformat() if pending.last_decided_at else None
                ),
            )

        # Per-phase status snapshot for the UI (5 entries).
        # Status computed from actual approval rows:
        #   - Past phases (index < current): approved if approval row exists
        #   - Current phase: "current"
        #   - Future phases (index > current): "pending"
        per_phase: list[dict] = []
        current_idx = AVAILABLE_PHASES.index(project.current_phase) if project.current_phase in AVAILABLE_PHASES else -1

        # Fetch all approvals for this project to determine past phases
        all_approvals = db.execute(
            select(Approval).where(Approval.project_id == project_id)
        ).scalars().all()
        approved_phases = {a.phase for a in all_approvals if a.decision == "approved"}

        for idx, phase_name in enumerate(AVAILABLE_PHASES):
            if idx < current_idx:
                # Past phase: approved if there's an approval row
                status_value = "approved" if phase_name in approved_phases else "pending"
            elif idx == current_idx:
                status_value = "current"
            else:
                # Future phase
                status_value = "pending"
            per_phase.append(
                {
                    "phase": phase_name,
                    "label": PHASE_LABELS.get(phase_name, phase_name),
                    "status": status_value,
                }
            )

        return PhasesOut(
            phases=per_phase,
            current_phase=project.current_phase or "requerimientos",
            phase_ready=project.phase_ready,
            available_phases=AVAILABLE_PHASES,
            pending_decision=pending_out,
        )
    finally:
        db.close()


# REQ-SA-13, REQ-SA-14, REQ-SA-15, REQ-SA-28, REQ-SA-30, REQ-SA-34:
# POST /api/projects/{id}/phase/{phase}/decision is the canonical decision
# endpoint for the 4 HU10-owned phases. ``requerimientos`` keeps F05's
# /api/elicitation/decision endpoint as its owner path (REQ-SA-36).
@router.post(
    "/{project_id}/phase/{phase}/decision",
    response_model=PhaseDecisionOut,
)
async def post_phase_decision(
    project_id: int,
    phase: str,
    body: PhaseDecisionIn,
    current_user: dict = Depends(get_current_user),
):
    """Record a phase decision (HU10-owned phases only).

    Returns:
        200 + PhaseDecisionOut on success.
        409 with typed body on phase_mismatch or decision_conflict.
        422 on invalid phase/action (forwarded from PhaseDecisionError).
        404 when the project does not exist or is not owned by the caller.
    """
    from app.core.phase_decisions import (
        IDEMPOTENCY_WINDOW_SECONDS,
        InvalidActionError,
        InvalidPhaseError,
        PhaseDecisionError,
        PhaseMismatchError,
        record_decision,
    )

    if phase not in AVAILABLE_PHASES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_phase",
                "phase": phase,
                "available_phases": AVAILABLE_PHASES,
            },
        )
    # REQ-SA-36: HU10 owns everything except ``requerimientos`` (F05).
    if phase == "requerimientos":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "wrong_owner",
                "phase": "requerimientos",
                "canonical_endpoint": "/api/projects/{id}/elicitation/decision",
                "owner": "F05",
            },
        )

    # action sanity (REQ-SA-14). The helper also validates, but we 422 here
    # before opening the DB to keep error paths tight.
    if body.action not in ("approve", "modify", "reject"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_action", "action": body.action},
        )
    if body.action == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "missing_feedback", "action": "modify"},
        )

    _require_project(current_user["user_id"], project_id)

    db = SessionLocal()
    try:
        result = record_decision(
            db,
            user_id=current_user["user_id"],
            project_id=project_id,
            phase=phase,
            action=body.action,
            feedback=body.feedback,
            payload=body.payload,
            idempotency_key=body.idempotency_key,
            previous_output=body.previous_output,
        )
        db.commit()
    except PhaseMismatchError as exc:
        # REQ-SA-28: typed 409 body; NEVER str(exc).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "phase_mismatch",
                "current_phase": exc.current_phase,
                "requested_phase": exc.requested_phase,
            },
        )
    except (InvalidPhaseError, InvalidActionError) as exc:
        # REQ-SA-34: structured detail, never str(exc). Use the exception
        # class name as a stable, non-leaking identifier.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "validation_error", "kind": type(exc).__name__},
        )
    except PhaseDecisionError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"error": "phase_decision_error", "kind": type(exc).__name__},
        )
    finally:
        db.close()

    decided_at = result.approval.created_at or _now_utc()
    return PhaseDecisionOut(
        decision_id=result.approval.id,
        action=body.action,
        phase=phase,
        project_id=project_id,
        next_phase=result.next_phase,
        decided_at=decided_at.isoformat() if hasattr(decided_at, "isoformat") else str(decided_at),
        idempotent=result.idempotent,
    )


def _now_utc():
    """Helper for decided_at fallback when approval.created_at is None."""
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)


# REQ-SA-36: /advance checks the HU10 approval record for HU10-owned phases
# before flipping ``phase_ready``. F05 keeps sole ownership of
# ``requerimientos`` (REQ-SA-1 / REQ-PA-HU10-5).
@router.post("/{project_id}/advance", response_model=PhaseAdvanceOut)
async def advance_phase(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Advance to the next phase. REQ-SA-36: HU10-owned phases require a
    recent ``approved`` row before this endpoint flips ``phase_ready``."""
    from app.core.phase_decisions import (
        PhaseNotApprovedError,
        assert_hu10_approval_for_current_phase,
    )

    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        # FOR UPDATE lock to prevent race conditions with concurrent reject
        project = db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id
            ).with_for_update()
        ).scalar_one_or_none()
        if project is None:
            exists = db.execute(
                select(Project).where(Project.id == project_id)
            ).scalar_one_or_none()
            if exists:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

        # REQ-SA-36: HU10 gate first. MUST run before phase_ready check so a
        # project that has phase_ready=True from a stale write still trips the
        # canonical owner check.
        try:
            assert_hu10_approval_for_current_phase(db, project_id=project_id)
        except PhaseNotApprovedError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "phase_not_approved", "phase": exc.phase},
            )

        if not project.phase_ready:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La fase actual todavía no está completa. No puedes avanzar aún.",
            )

        idx = AVAILABLE_PHASES.index(project.current_phase) if project.current_phase in AVAILABLE_PHASES else -1
        if idx == -1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fase no reconocida")
        if idx == len(AVAILABLE_PHASES) - 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ya estás en la última fase")

        project.current_phase = AVAILABLE_PHASES[idx + 1]
        project.phase_ready = False
        db.commit()
        db.refresh(project)

        label = PHASE_LABELS.get(project.current_phase, project.current_phase or "")
        return PhaseAdvanceOut(
            current_phase=project.current_phase,
            phase_ready=project.phase_ready,
            message=f"Fase avanzada a '{label}'",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()


# REQ-SA-23: POST /api/projects/{id}/mark-ready is REMOVED. v1 left this as a
# temporary dev button; v2 retires it permanently. Returning 404 here is the
# safest "endpoint removed" signal for clients that still call it.
# (If a cleaner is desired, future work can drop the route entirely; for now
# the 404 detail names the replacement so frontend redirects work.)
@router.post("/{project_id}/mark-ready")
async def mark_ready_removed(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """REQ-SA-23: retired. Use POST /phase/{phase}/decision instead."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "endpoint_removed",
            "endpoint": "mark-ready",
            "replacement": "POST /api/projects/{id}/phase/{phase}/decision",
            "removed_in": "hu10-staged-approvals-v2",
        },
    )