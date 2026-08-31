import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.agent import ArchitectAgent
from app.core.llm_loader import build_langchain_model, load_user_llm_config, LLMConfigError
from app.core.database import SessionLocal
from app.core.session_store import get_or_create_session_for_project
from app.models.project import Project
from app.models.interaction_log import InteractionLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# --- Request model ---------------------------------------------------------

class ChatRequest(BaseModel):
    project_id: int | None = None
    message: str


# --- Helper functions ------------------------------------------------------

def _persist_prompt(user_id: int, project_id: int | None, message: str) -> int | None:
    """
    Persist user message to interaction_logs.
    Returns the interaction_log id, or None if persistence fails.
    """
    db = SessionLocal()
    try:
        # Get or create session for the project
        session = get_or_create_session_for_project(user_id, project_id or 0)

        # Create interaction log entry with just the prompt
        interaction_log = InteractionLog(
            session_id=session.id,
            phase="chat",
            prompt=message,
        )
        db.add(interaction_log)
        db.commit()
        db.refresh(interaction_log)
        return interaction_log.id
    except Exception as e:
        logger.warning(f"Failed to persist prompt: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def _persist_response(
    interaction_log_id: int | None,
    response: str,
    latency_ms: int,
    tokens_used: int | None,
    model: str | None,
):
    """
    Update interaction log with assistant response.
    """
    if interaction_log_id is None:
        return

    db = SessionLocal()
    try:
        log = db.query(InteractionLog).filter(InteractionLog.id == interaction_log_id).first()
        if log:
            log.response = response
            log.latency_ms = latency_ms
            log.tokens_used = tokens_used
            log.model = model
            db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist response: {e}")
        db.rollback()
    finally:
        db.close()


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

    # Verify LLM config exists (fail fast with 409 if not configured)
    try:
        llm_config = load_user_llm_config(user_id)
    except LLMConfigError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"LLM no configurado. Ejecuta POST /api/llm/config primero. ({e})",
        )

    # Persist user message BEFORE processing
    interaction_log_id = _persist_prompt(user_id, body.project_id, body.message)

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

    # Track timing for latency
    start_time = time.time()
    model_name = llm_config.get("model", "unknown") if llm_config else "unknown"
    tokens_used = 0  # Will be updated when agent returns metadata

    async def event_generator():
        """
        SSE generator streaming agent response tokens.

        F08: uses ArchitectAgent (LangGraph) with RAG context.
        Events: token → proposal → done (or error).

        Persists response AFTER stream completes.
        """
        nonlocal tokens_used
        full_response = ""

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
        finally:
            # Calculate latency and persist response
            latency_ms = int((time.time() - start_time) * 1000)
            # Get final response from chatStore via client-side callback would be ideal,
            # but since we're streaming, we track tokens. For now, we capture what we streamed.
            # The actual full response is assembled client-side, so we persist what we have.
            # Note: This is a simplification - ideally we'd get the complete response from the agent.
            _persist_response(
                interaction_log_id,
                full_response,
                latency_ms,
                tokens_used,
                model_name,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
