from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.auth.validators import ValidationError
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


class PhaseOut(BaseModel):
    current_phase: str
    phase_ready: bool
    available_phases: list[str]


class PhaseAdvanceOut(BaseModel):
    current_phase: str
    phase_ready: bool
    message: str


AVAILABLE_PHASES = ["requerimientos", "propuesta", "refinamiento", "revision"]
PHASE_LABELS = {
    "requerimientos": "Requerimientos",
    "propuesta": "Propuesta",
    "refinamiento": "Refinamiento",
    "revision": "Revisión",
}


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
    from app.core.database import SessionLocal
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
    project = _require_project(current_user["user_id"], project_id)
    from app.core.database import SessionLocal

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


@router.post("/{project_id}/mark-ready", response_model=dict)
async def mark_ready(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Mark the current phase as ready to advance (temporary dev button)."""
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

        project.phase_ready = True
        db.commit()
        return {"phase_ready": True, "message": "Fase marcada como completa"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()
