"""
GET /api/diagrams/history — lista los diagramas (attachments tipo
"screenshot") generados en un proyecto, ordenados del más reciente al
más antiguo (HU6: "Historial de versiones del diagrama").
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.models.message import Message
from app.models.project import Project

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