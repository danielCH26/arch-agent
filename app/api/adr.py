"""ADR del proyecto (fase Revisión).

GET  /api/projects/{id}/adr  — el último ADR generado (o ``markdown: null``).
POST /api/projects/{id}/adr  — genera (o regenera) el ADR y lo guarda.

El ADR se guarda en ``engram_state[project_id]["adr"]`` de la sesión del
usuario, igual que el resumen de elicitación y el snapshot de la propuesta,
para que se vea al recargar sin volver a llamar al LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
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
from app.models.session import UserSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["adr"])


class AdrOut(BaseModel):
    markdown: Optional[str]
    generated_at: Optional[str]
    # False cuando la guía práctica (sección 7) no se pudo redactar con el LLM.
    guide_complete: bool = False


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@router.get("/{project_id}/adr", response_model=AdrOut)
async def get_adr(project_id: int, current_user: dict = Depends(get_current_user)):
    user_id = int(current_user["user_id"])
    _require_project(user_id, project_id)

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        project_state = ((session_row.engram_state or {}) if session_row else {}).get(
            str(project_id)
        )
        stored = (project_state or {}).get(ADR_STATE_KEY) if isinstance(project_state, dict) else None
        if not isinstance(stored, dict) or not stored.get("markdown"):
            return AdrOut(markdown=None, generated_at=None, guide_complete=False)
        return AdrOut(
            markdown=stored["markdown"],
            generated_at=stored.get("generated_at"),
            guide_complete=bool(stored.get("guide_complete")),
        )
    finally:
        db.close()


@router.post("/{project_id}/adr", response_model=AdrOut)
async def generate_adr(project_id: int, current_user: dict = Depends(get_current_user)):
    """Genera el ADR con lo decidido hasta ahora.

    409 si todavía no hay una propuesta aprobada. Si el LLM no está
    configurado o falla, el ADR se genera igual sin la guía práctica.
    """
    user_id = int(current_user["user_id"])
    _require_project(user_id, project_id)

    db = SessionLocal()
    try:
        try:
            ctx = collect_adr_context(db, user_id=user_id, project_id=project_id)
        except AdrNotReadyError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
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

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session_row is None:
            session_row = UserSession(user_id=user_id, engram_state={})
            db.add(session_row)
        engram_state = dict(session_row.engram_state or {})
        raw = engram_state.get(str(project_id))
        project_state = dict(raw) if isinstance(raw, dict) else {}
        project_state[ADR_STATE_KEY] = {
            "markdown": markdown,
            "generated_at": _iso(generated_at),
            "guide_complete": guide is not None,
        }
        engram_state[str(project_id)] = project_state
        session_row.engram_state = engram_state
        flag_modified(session_row, "engram_state")
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

    return AdrOut(
        markdown=markdown,
        generated_at=_iso(generated_at),
        guide_complete=guide is not None,
    )
