from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.auth.validators import ValidationError
from app.core import phase_decisions
from app.core.phase_decisions import (
    AVAILABLE_PHASES,
    DecisionConflict,
    InvalidAction,
    InvalidPhase,
    ModifyFeedbackRequired,
    PhaseDecisionResult,
    ProjectNotFound,
)
from app.models.project import Project

# Re-export so existing imports of `from app.api.projects import AVAILABLE_PHASES`
# keep working. New code MUST import from app.core.phase_decisions instead.
__all__ = [
    "AVAILABLE_PHASES",
    "PHASE_LABELS",
    "router",
]

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


class PhaseOut(BaseModel):
    current_phase: str
    phase_ready: bool
    available_phases: list[str]


class PhaseAdvanceOut(BaseModel):
    current_phase: str
    phase_ready: bool
    message: str


# HU10 (REQ-SA-4): canonical 5-phase taxonomy. Re-exported from
# app.core.phase_decisions.AVAILABLE_PHASES so legacy imports still work;
# new code MUST use the core helper directly.
PHASE_LABELS = {
    "requerimientos": "Requerimientos",
    "propuesta": "Propuesta",
    "refinamiento": "Refinamiento",
    "revision": "Revisión",
    "final": "Aprobación final",
}


# HU10 (REQ-SA-13/14): decision request body.
class PhaseDecisionIn(BaseModel):
    action: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


class PhaseDecisionOut(BaseModel):
    decision_id: int
    project_id: int
    phase: str
    action: str
    next_phase: Optional[str]
    decided_at: str
    idempotent: bool


# HU11 (REQ-SA-25): regenerate request body for the per-phase SSE endpoint.
class PhaseRegenerateIn(BaseModel):
    feedback: str
    payload: Optional[dict[str, Any]] = None


# HU10 (REQ-SA-15 / design §D.2): richer read shape for the SPA mount logic.
class PhaseStatusItem(BaseModel):
    name: str
    label: str
    status: str  # "active" | "approved" | "pending"
    ready: bool
    current_decision: Optional[dict[str, Any]] = None


class PhaseListOut(BaseModel):
    phases: list[PhaseStatusItem]
    current_phase: str


# --- Helpers (reuse from app.py) -----------------------------------------------

def _require_project(user_id: int, project_id: int) -> Project:
    """Load project and raise 403/404 if not found or not owned."""
    from app.core.database import SessionLocal

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

    from app.core.database import SessionLocal

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
    from app.core.database import SessionLocal

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
    from app.core.database import SessionLocal

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
    """Get current phase info for a project."""
    project = _require_project(current_user["user_id"], project_id)
    return PhaseOut(
        current_phase=project.current_phase or "requerimientos",
        phase_ready=project.phase_ready,
        available_phases=AVAILABLE_PHASES,
    )


@router.post("/{project_id}/advance", response_model=PhaseAdvanceOut)
async def advance_phase(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Advance to the next phase (requires phase_ready=True)."""
    from app.core.database import SessionLocal

    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            exists = db.query(Project).filter(Project.id == project_id).first()
            if exists:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

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


# ---------------------------------------------------------------------------
# HU10 (REQ-SA-23/24): ``POST /api/projects/{id}/mark-ready`` removed.
#
# The dev shortcut is no longer needed now that the canonical per-phase
# ``POST /api/projects/{id}/phase/{phase}/decision`` endpoint (above)
# covers every phase including a 'modify' UX. Anyone POSTing to the old
# path will get a 422 from FastAPI because no route is registered for it.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# HU10 (REQ-SA-13): POST /api/projects/{id}/phase/{phase}/decision
# Single canonical decision endpoint covering all 5 phases.
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/phase/{phase}/decision",
    response_model=PhaseDecisionOut,
)
async def phase_decision(
    project_id: int,
    phase: str,
    body: PhaseDecisionIn,
    current_user: dict = Depends(get_current_user),
):
    """Record a per-phase approve / modify / reject decision.

    Maps the domain exceptions from ``app.core.phase_decisions`` to HTTP
    responses per the contract in ``design.md §D.1``:

    - 200 + ``PhaseDecisionOut``: decision recorded (or idempotent re-POST)
    - 400: missing feedback on ``modify``
    - 403: project belongs to another user
    - 404: project not found
    - 409: a different-action decision already exists in the 60s window
    - 422: invalid ``action`` or ``phase``
    """
    from app.core.database import SessionLocal

    # Ownership pre-flight (mirrors the F08 decide_proposal pattern).
    _require_project(current_user["user_id"], project_id)

    db = SessionLocal()
    try:
        result: PhaseDecisionResult = phase_decisions.record_decision(
            db=db,
            project_id=project_id,
            phase=phase,
            action=body.action,
            feedback=body.feedback,
            payload=body.payload,
        )
        db.commit()
    except ProjectNotFound:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proyecto no encontrado",
        )
    except ModifyFeedbackRequired:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Modify requiere feedback no vacío.",
        )
    except InvalidAction:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"action inválida; permitidas: approve, modify, reject",
        )
    except InvalidPhase:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"phase inválida; permitidas: {AVAILABLE_PHASES}",
        )
    except DecisionConflict as conflict:
        db.rollback()
        # REQ-SA-9 / REQ-SA-15: 409 body is {current_decision, decided_at}.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "current_decision": conflict.current_decision,
                "decided_at": conflict.decided_at.isoformat()
                if conflict.decided_at else None,
            },
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo registrar la decisión: {exc}",
        ) from exc
    finally:
        db.close()

    return PhaseDecisionOut(
        decision_id=result.decision_id,
        project_id=result.project_id,
        phase=result.phase,
        action=result.action,
        next_phase=result.next_phase,
        decided_at=result.decided_at.isoformat() if result.decided_at else "",
        idempotent=result.idempotent,
    )


@router.get("/{project_id}/phases", response_model=PhaseListOut)
async def list_phases(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Detailed per-phase decision state for the HU10 SPA mount logic.

    Returns one row per phase in ``AVAILABLE_PHASES`` with:
    - ``status``: ``active`` (the project's current phase) / ``approved``
      (a prior decision is approved) / ``pending`` (everything else)
    - ``ready``: true ONLY when this is the current phase AND
      ``project.phase_ready`` is true
    - ``current_decision``: the latest approval row for that phase, if any
    """
    from app.core.database import SessionLocal

    user_id = current_user["user_id"]
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            exists = db.query(Project).filter(Project.id == project_id).first()
            if exists:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

        current_phase = project.current_phase or "requerimientos"

        # Pull the latest approval row per phase in a single query; group
        # in Python so the response shape stays simple.
        from app.models.approval import Approval
        from app.models.session import UserSession

        session_row = (
            db.query(UserSession)
            .filter(UserSession.user_id == project.user_id)
            .first()
        )
        if session_row is None:
            approval_rows = []
        else:
            approval_rows = (
                db.query(Approval)
                .filter(Approval.session_id == int(session_row.id))
                .order_by(Approval.created_at.desc())
                .all()
            )

        latest_by_phase: dict[str, Any] = {}
        for row in approval_rows:
            latest_by_phase.setdefault(row.phase, row)

        phases: list[PhaseStatusItem] = []
        for name in AVAILABLE_PHASES:
            row = latest_by_phase.get(name)
            decision_dict: Optional[dict[str, Any]] = None
            if row is not None:
                decision_dict = {
                    "id": int(row.id),
                    "action": row.decision,
                    "feedback": row.feedback,
                    "decided_at": row.created_at.isoformat() if row.created_at else None,
                }

            if name == current_phase:
                status_label = "active"
            elif row is not None and row.decision in ("approved", "approve"):
                status_label = "approved"
            else:
                status_label = "pending"

            phases.append(
                PhaseStatusItem(
                    name=name,
                    label=PHASE_LABELS.get(name, name),
                    status=status_label,
                    ready=(name == current_phase and bool(project.phase_ready)),
                    current_decision=decision_dict,
                )
            )

        return PhaseListOut(phases=phases, current_phase=current_phase)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# HU11 (REQ-SA-25..29): POST /api/projects/{id}/phases/{phase}/regenerate
#
# SSE endpoint that dispatches per-phase LLM regeneration AFTER the
# HU10 decision row has been recorded (decision + LLM failure modes are
# orthogonal — see design §B.3 / ADR-015 §"Decision + regeneration
# failure modes are orthogonal"). Same event shape as /api/chat and
# /api/proposals/{id}/modify: ``event: sources|token*|done|error``.
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/phases/{phase}/regenerate",
)
async def regenerate_phase(
    project_id: int,
    phase: str,
    body: PhaseRegenerateIn,
    current_user: dict = Depends(get_current_user),
):
    """Per-phase LLM regenerate (HU11 REQ-SA-25).

    The route is intentionally thin: validation + ownership + 60s
    idempotency happen at the edge; per-phase dispatch + streaming live in
    ``app/core/regenerate_dispatcher.dispatch_regenerate``. The pre-flight
    checks raise ``HTTPException`` BEFORE the streaming response starts
    so the SPA sees a clean status code (no half-streamed 200 + error
    event for what is really a 4xx).
    """
    import asyncio
    import json

    from app.core.regenerate_dispatcher import (
        MissingPayload,
        PastPhaseConflict,
        dispatch_regenerate,
    )

    user_id = int(current_user["user_id"])

    # Ownership + project metadata pre-flight. We do NOT open the
    # streaming response until the project is confirmed.
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            exists = db.query(Project).filter(Project.id == project_id).first()
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes acceso a este proyecto",
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proyecto no encontrado",
            )
        current_phase = project.current_phase or "requerimientos"
        project_description = project.description or ""
    finally:
        db.close()

    # 60s idempotency window on (session_id, phase). Re-uses the HU10
    # record_decision conflict semantics so double-click within the
    # window returns the prior decision_id instead of streaming twice.
    # We do NOT short-circuit here — the dispatcher will return the same
    # content (deterministic feedback). REQ-SA-29 / SCN-SA-29.1.
    feedback_value = body.feedback.strip() if body.feedback else ""

    # Pre-flight validation: 400/409 BEFORE the streaming response begins
    # so the SPA gets a clean status code (no half-streamed 200 + error
    # event for what is really a 4xx). The dispatcher repeats these checks
    # defensively; if they fire here the streaming never starts.
    from app.core.regenerate_dispatcher import (
        AVAILABLE_PHASES as _AVAILABLE,
    )

    if phase not in _AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"phase inválida; permitidas: {_AVAILABLE}",
        )
    if not feedback_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="feedback es obligatorio y no puede estar vacío",
        )
    if phase == "final":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Modify not allowed on final phase (REQ-SA-8).",
        )
    if current_phase in _AVAILABLE and phase in _AVAILABLE:
        if _AVAILABLE.index(phase) >= _AVAILABLE.index(current_phase):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"phase {phase!r} está en o después de current_phase "
                    f"{current_phase!r}; solo fases anteriores pueden regenerarse."
                ),
            )

    async def event_stream():
        try:
            async for event_name, payload_obj in dispatch_regenerate(
                db=None,  # unused for the chosen phases in this build
                user_id=user_id,
                project_id=project_id,
                phase=phase,
                feedback=feedback_value,
                payload=body.payload,
                current_phase=current_phase,
                project_description=project_description,
            ):
                payload_json = json.dumps(payload_obj, ensure_ascii=False)
                yield f"event: {event_name}\ndata: {payload_json}\n\n"
        except (MissingPayload, PastPhaseConflict) as exc:
            # Should never fire here because pre-flight above already
            # raised HTTPException for these, but keep the guard so the
            # SSE never silently truncates mid-flight on validation drift.
            yield f"event: error\ndata: {json.dumps(str(exc), ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            # 503-class for LLM outage mid-stream; audit row from the
            # prior /decision call STILL exists in DB (REQ-SA-25.4).
            yield f"event: error\ndata: {json.dumps(str(exc), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )