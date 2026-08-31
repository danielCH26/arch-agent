import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.agent import ArchitectAgent
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.database import SessionLocal
from app.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# --- Request model ---------------------------------------------------------

class ChatRequest(BaseModel):
    project_id: int | None = None
    message: str


# --- Route -----------------------------------------------------------------

@router.post("")
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream agent chat responses as SSE.

    POST /api/chat  →  text/event-stream
        body: {"project_id": int | null, "message": str}

    Returns:
        200 text/event-stream — tokens as "event: token" + final "event: done"
        400 — no message provided
        401 — invalid JWT
        404 — project not found or not owned
        409 — LLM not configured for user
    """
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mensaje vacío")

    user_id = current_user["user_id"]

    # Validate project ownership if provided
    if body.project_id is not None:
        db = SessionLocal()
        try:
            project = db.query(Project).filter(
                Project.id == body.project_id,
                Project.user_id == user_id,
            ).first()
            if project is None:
                exists = db.query(Project).filter(
                    Project.id == body.project_id
                ).first()
                if exists:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="No tienes acceso a este proyecto",
                    )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Proyecto no encontrado",
                )
        finally:
            db.close()

    # Build the LLM model early to fail fast if not configured (409)
    try:
        build_langchain_model(user_id)
    except LLMConfigError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM no configurado. Ejecuta POST /api/llm/config primero.",
        )

    # Project context for the agent prompt
    project_context = ""
    if body.project_id is not None:
        db = SessionLocal()
        try:
            project = db.query(Project).filter(
                Project.id == body.project_id,
                Project.user_id == user_id,
            ).first()
            if project:
                project_context = (
                    f"Nombre: {project.name}\n"
                    f"Descripción: {project.description or 'sin descripción'}\n"
                    f"Fase actual: {project.current_phase or 'sin asignar'}"
                )
        finally:
            db.close()

    async def event_generator():
        """
        SSE generator streaming agent response tokens.

        F08: uses ArchitectAgent (LangGraph) with RAG context.
        Events: token → proposal → done (or error).
        """
        try:
            # R13: agent instantiated PER REQUEST (never global)
            agent = ArchitectAgent(user_id=user_id, project_id=body.project_id)

            proposal_payload = None
            async for event in agent.stream(
                message=body.message,
                project_context=project_context,
            ):
                if event["type"] == "token":
                    yield f"event: token\ndata: {json.dumps(event['content'], ensure_ascii=False)}\n\n"
                elif event["type"] == "proposal":
                    proposal_payload = event["proposal"]
                    payload = json.dumps(
                        {"has_proposal": proposal_payload is not None},
                        ensure_ascii=False,
                    )
                    yield f"event: proposal\ndata: {payload}\n\n"
                elif event["type"] == "done":
                    break

            yield f"event: done\ndata: null\n\n"
        except LLMConfigError:
            yield f"event: error\ndata: {json.dumps('LLM no configurado', ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Agent stream failed")
            yield f"event: error\ndata: {json.dumps(f'Error del agente: {e}', ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
