"""ADR del proyecto (fase Revisión).

GET  /api/projects/{id}/adr          — el último ADR generado (o ``markdown: null``).
POST /api/projects/{id}/adr          — genera o regenera el ADR. Con ``feedback``
                                       registra los cambios pedidos y los aplica.
POST /api/projects/{id}/adr/approve  — aprueba el ADR y da el proyecto por
                                       terminado (la fase queda lista).

El ADR se guarda en ``engram_state[project_id]["adr"]`` de la sesión del
usuario, igual que el resumen de elicitación y el snapshot de la propuesta,
para que se vea al recargar sin volver a llamar al LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user
from app.api.projects import _require_project
from app.core.adr_generator import (
    ADR_STATE_KEY,
    AdrNotReadyError,
    collect_adr_context,
    generate_llm_sections,
    render_adr_markdown,
)
from app.core.database import SessionLocal
from app.core.langfuse_tracer import flush as flush_langfuse
from app.core.langfuse_tracer import get_langfuse_handler
from app.core.llm_loader import LLMConfigError, build_langchain_model
from app.core.session_store import record_approval_decision
from app.models.project import Project
from app.models.session import UserSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["adr"])

# Fase con la que se registran las decisiones sobre el ADR en `approvals`.
REVISION_PHASE = "revision"


class AdrGenerateIn(BaseModel):
    # Cambios pedidos al revisar el ADR ("Solicitar cambios"). Vacío = regenerar.
    feedback: Optional[str] = Field(default=None, max_length=2000)


class AdrOut(BaseModel):
    markdown: Optional[str]
    generated_at: Optional[str]
    # False cuando la guía práctica (sección 7) no se pudo redactar con el LLM.
    guide_complete: bool = False
    # Cambios pedidos en la revisión, en orden.
    feedback_history: list[str] = []
    # ISO del momento en que se aprobó el ADR (proyecto terminado), o None.
    approved_at: Optional[str] = None


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _session_row(db, user_id: int) -> UserSession:
    row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
    if row is None:
        row = UserSession(user_id=user_id, engram_state={})
        db.add(row)
    return row


def _stored_adr(session_row: Optional[UserSession], project_id: int) -> dict:
    if session_row is None:
        return {}
    project_state = (session_row.engram_state or {}).get(str(project_id))
    if not isinstance(project_state, dict):
        return {}
    stored = project_state.get(ADR_STATE_KEY)
    return dict(stored) if isinstance(stored, dict) else {}


def _save_adr(session_row: UserSession, project_id: int, stored: dict) -> None:
    engram_state = dict(session_row.engram_state or {})
    raw = engram_state.get(str(project_id))
    project_state = dict(raw) if isinstance(raw, dict) else {}
    project_state[ADR_STATE_KEY] = stored
    engram_state[str(project_id)] = project_state
    session_row.engram_state = engram_state
    flag_modified(session_row, "engram_state")


def _out(stored: dict) -> AdrOut:
    if not stored.get("markdown"):
        return AdrOut(markdown=None, generated_at=None)
    return AdrOut(
        markdown=stored["markdown"],
        generated_at=stored.get("generated_at"),
        guide_complete=bool(stored.get("guide_complete")),
        feedback_history=list(stored.get("feedback_history") or []),
        approved_at=stored.get("approved_at"),
    )


@router.get("/{project_id}/adr", response_model=AdrOut)
async def get_adr(project_id: int, current_user: dict = Depends(get_current_user)):
    user_id = int(current_user["user_id"])
    _require_project(user_id, project_id)

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        return _out(_stored_adr(session_row, project_id))
    finally:
        db.close()


@router.post("/{project_id}/adr", response_model=AdrOut)
async def generate_adr(
    project_id: int,
    body: Optional[AdrGenerateIn] = Body(default=None),
    current_user: dict = Depends(get_current_user),
):
    """Genera el ADR con lo decidido hasta ahora.

    Con ``feedback`` se registra un "modify" en la fase Revisión, se suma al
    historial de cambios y el LLM lo aplica. Pedir cambios reabre el proyecto
    si ya estaba aprobado. 409 si todavía no hay una propuesta aprobada. Si el
    LLM no está configurado o falla, el ADR se genera igual sin la guía.
    """
    user_id = int(current_user["user_id"])
    _require_project(user_id, project_id)
    feedback = (body.feedback or "").strip() if body else ""

    db = SessionLocal()
    try:
        stored = _stored_adr(
            db.query(UserSession).filter(UserSession.user_id == user_id).first(), project_id
        )
        history = list(stored.get("feedback_history") or [])
        if feedback:
            # Se registra antes de juntar el contexto para que aparezca en el
            # historial de decisiones del propio ADR.
            record_approval_decision(
                db,
                user_id=user_id,
                phase=REVISION_PHASE,
                decision="modify",
                feedback=feedback,
                project_id=project_id,
            )
            history.append(feedback)
        # Un ADR nuevo (con o sin cambios) vuelve a necesitar aprobación: el
        # proyecto deja de estar terminado hasta que se apruebe otra vez.
        project = db.get(Project, project_id)
        if project is not None:
            project.phase_ready = False
        db.commit()
        try:
            ctx = collect_adr_context(db, user_id=user_id, project_id=project_id)
        except AdrNotReadyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        ctx.revision_feedback = history
    finally:
        # La llamada al LLM puede tardar: no se mantiene la conexión abierta.
        db.close()

    guide: Optional[str] = None
    try:
        model = build_langchain_model(user_id)
    except LLMConfigError:
        logger.warning("ADR sin guía: el usuario %s no tiene LLM configurado", user_id)
        model = None
    if model is not None:
        handler = get_langfuse_handler()
        callbacks = [handler] if handler is not None else None
        guide = await generate_llm_sections(model, ctx, callbacks=callbacks)
        if callbacks:
            flush_langfuse()

    generated_at = datetime.now(tz=timezone.utc)
    markdown = render_adr_markdown(ctx, llm_sections=guide, generated_at=generated_at)

    new_stored = {
        "markdown": markdown,
        "generated_at": _iso(generated_at),
        "guide_complete": guide is not None,
        "feedback_history": history,
        # Un ADR nuevo vuelve a necesitar aprobación.
        "approved_at": None,
    }
    db = SessionLocal()
    try:
        _save_adr(_session_row(db, user_id), project_id, new_stored)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("No se pudo guardar el ADR del proyecto %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo guardar el ADR. Inténtalo de nuevo.",
        ) from exc
    finally:
        db.close()

    return _out(new_stored)


@router.post("/{project_id}/adr/approve", response_model=AdrOut)
async def approve_adr(project_id: int, current_user: dict = Depends(get_current_user)):
    """Aprueba el ADR: el proyecto queda terminado (fase lista)."""
    user_id = int(current_user["user_id"])
    _require_project(user_id, project_id)

    db = SessionLocal()
    try:
        session_row = _session_row(db, user_id)
        stored = _stored_adr(session_row, project_id)
        if not stored.get("markdown"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Primero genera el ADR para poder aprobarlo.",
            )
        if not stored.get("approved_at"):
            record_approval_decision(
                db,
                user_id=user_id,
                phase=REVISION_PHASE,
                decision="approve",
                feedback=None,
                project_id=project_id,
            )
            stored["approved_at"] = _iso(datetime.now(tz=timezone.utc))
            _save_adr(session_row, project_id, stored)
        project = db.get(Project, project_id)
        if project is not None:
            project.phase_ready = True
        db.commit()
        return _out(stored)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("No se pudo aprobar el ADR del proyecto %s", project_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo aprobar el ADR. Inténtalo de nuevo.",
        ) from exc
    finally:
        db.close()
