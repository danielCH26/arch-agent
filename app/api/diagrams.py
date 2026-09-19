"""
GET /api/diagrams/history — lista los diagramas (attachments tipo
"screenshot") generados en un proyecto, ordenados del más reciente al
más antiguo (HU6: "Historial de versiones del diagrama").
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_current_user
from app.core.attachment_tokens import build_attachment_url
from app.core.database import SessionLocal
from app.core.session_store import record_approval_decision
from app.models.message import Message
from app.models.project import Project
from pydantic import BaseModel

router = APIRouter(prefix="/api/diagrams", tags=["diagrams"])


class DiagramVersionOut(BaseModel):
    message_id: int
    url: str
    filename: Optional[str] = None
    created_at: str


class DiagramHistoryOut(BaseModel):
    diagrams: list[DiagramVersionOut]


@router.get("/history", response_model=DiagramHistoryOut)
def diagram_history(
    project_id: int = Query(..., ge=1),
    current_user: dict = Depends(get_current_user),
) -> DiagramHistoryOut:
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

        # Hallazgo #10 (revisión feature/hu6-diagrama): antes traía TODOS
        # los mensajes del asistente del proyecto (con `content` completo,
        # que puede ser largo) sin límite. Ahora: solo columnas necesarias
        # (`with_entities`), solo filas que realmente tengan adjuntos, y un
        # tope razonable de mensajes recientes a inspeccionar.
        HISTORY_MESSAGE_LOOKBACK = 200

        rows = (
            db.query(Message)
            .filter(
                Message.project_id == project_id,
                Message.user_id == user_id,
                Message.role == "assistant",
                Message.attachments != None,  # noqa: E711 (comparación JSONB, no bool)
                Message.attachments != [],
            )
            .order_by(Message.created_at.desc())
            .limit(HISTORY_MESSAGE_LOOKBACK)
            .with_entities(Message.id, Message.created_at, Message.attachments)
            .all()
        )

        versions: list[DiagramVersionOut] = []
        for row in rows:
            for att in row.attachments or []:
                if att.get("kind") == "screenshot" and att.get("id"):
                    versions.append(
                        DiagramVersionOut(
                            message_id=row.id,
                            # Bug fix (HU6): no reusar att["url"] tal cual —
                            # es el token firmado en el momento en que se
                            # genero el diagrama (TTL 5 min) y para cuando
                            # alguien abre el historial de versiones ya esta
                            # vencido casi siempre. Se re-firma aqui.
                            url=build_attachment_url(att["id"], user_id),
                            filename=att.get("filename"),
                            created_at=row.created_at.isoformat(),
                        )
                    )

        return DiagramHistoryOut(diagrams=versions)
    finally:
        db.close()

PHASE = "diagram"


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
    phase="diagram"), mismo mecanismo que /elicitation/decision y
    /proposal/decision.

    Antes lanzaba 400 si no había una `UserSession` todavía, mientras que
    /proposal/decision la creaba de forma perezosa con
    `ensure_user_session` -- un usuario podía aprobar la propuesta pero no
    el diagrama en su primera interacción. `record_approval_decision`
    unifica el criterio: la sesión se crea si falta, en vez de bloquear.
    """
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

        record_approval_decision(
            db,
            user_id=user_id,
            phase=PHASE,
            decision=body.decision,
            feedback=body.feedback,
            project_id=project_id,
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