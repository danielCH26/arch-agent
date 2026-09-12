"""
GET /api/diagrams/history — lista los diagramas (attachments tipo
"screenshot") generados en un proyecto, ordenados del más reciente al
más antiguo (HU6: "Historial de versiones del diagrama").
"""
from __future__ import annotations

from typing import Any,Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.models.message import Message
from app.models.project import Project
from pydantic import BaseModel
from app.models.approval import Approval
from app.models.session import UserSession

router = APIRouter(prefix="/api/diagrams", tags=["diagrams"])


@router.get("/history")
def diagram_history(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proyecto no encontrado",
            )

        rows = (
            db.query(Message)
            .filter(
                Message.project_id == project_id,
                Message.user_id == user_id,
                Message.role == "assistant",
            )
            .order_by(Message.created_at.desc())
            .all()
        )

        versions: list[dict[str, Any]] = []
        for row in rows:
            for att in row.attachments or []:
                if att.get("kind") == "screenshot":
                    versions.append(
                        {
                            "message_id": row.id,
                            "url": att["url"],
                            "filename": att.get("filename"),
                            "created_at": row.created_at.isoformat(),
                        }
                    )

        return {"diagrams": versions}
    finally:
        db.close()

from typing import Literal, Optional

from pydantic import BaseModel
from app.models.approval import Approval
from app.models.session import UserSession

PHASE = "diagram"

DECISION_TO_DB = {
    "approve": "approved",
    "modify": "modified",
    "reject": "rejected",
}


class DiagramDecisionIn(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None


class DiagramDecisionOut(BaseModel):
    decision: str
    message: str


@router.post("/decision", response_model=DiagramDecisionOut)
def decide_diagram(
    body: DiagramDecisionIn,
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
) -> DiagramDecisionOut:
    """Registra la decisión del usuario sobre el diagrama (tabla approvals,
    phase="diagram"), mismo mecanismo que /elicitation/decision."""
    if body.decision == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El feedback es obligatorio para 'modify'.",
        )

    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proyecto no encontrado",
            )

        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay una sesión activa para este proyecto.",
            )

        db.add(
            Approval(
                session_id=session_row.id,
                phase=PHASE,
                decision=DECISION_TO_DB[body.decision],
                feedback=body.feedback,
            )
        )
        db.commit()

        messages = {
            "approve": "Diagrama aprobado.",
            "modify": "Se registró tu solicitud de cambios.",
            "reject": "Diagrama rechazado.",
        }
        return DiagramDecisionOut(decision=body.decision, message=messages[body.decision])
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()