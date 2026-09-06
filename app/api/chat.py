import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.elicitation_agent import (
    ElicitationAgentError,
    FIRST_QUESTION,
    generate_summary,
    next_step,
)
from app.core.elicitation_state import (
    get_project_elicitation_state,
    save_project_elicitation_state,
)
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.database import SessionLocal
from app.core.rag import similarity_search
from app.models.project import Project
from app.models.session import UserSession

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)

RAG_MIN_SIMILARITY = 0.85


def _is_relevant(doc) -> bool:
    return (doc.metadata.get("similarity") or 0.0) >= RAG_MIN_SIMILARITY


# --- Request model ---------------------------------------------------------

class ChatRequest(BaseModel):
    project_id: int | None = None
    message: str


class ElicitationStatus(BaseModel):
    history: list[dict]
    current_question: str | None
    summary: dict | None
    completed: bool
    approved: bool


def _summary_text(summary: dict) -> str:
    """Formato legible y revisable del resumen estructurado para el chat."""
    def items(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- No especificado"

    return (
        "Resumen de requerimientos para validar\n\n"
        f"Problema\n{summary.get('problema', 'No especificado')}\n\n"
        f"Usuarios\n{summary.get('usuarios', 'No especificado')}\n\n"
        f"Funcionalidades\n{items(summary.get('funcionalidades', []))}\n\n"
        f"Restricciones\n{items(summary.get('restricciones', []))}\n\n"
        f"Calidad\n{items(summary.get('calidad', []))}\n\n"
        "Revísalo y apruébalo cuando refleje tus necesidades."
    )


def _require_project(db, user_id: int, project_id: int) -> Project:
    project = db.query(Project).filter(
        Project.id == project_id, Project.user_id == user_id
    ).first()
    if project is not None:
        return project
    exists = db.query(Project).filter(Project.id == project_id).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")


@router.get("/{project_id}/elicitation", response_model=ElicitationStatus)
async def get_elicitation_status(project_id: int, current_user: dict = Depends(get_current_user)):
    """Recupera la pregunta pendiente o el resumen de HU05 al reabrir el chat."""
    db = SessionLocal()
    try:
        project = _require_project(db, current_user["user_id"], project_id)
        if project.current_phase != "requerimientos":
            return ElicitationStatus(
                history=[], current_question=None, summary=None,
                completed=False, approved=False,
            )
        session = db.query(UserSession).filter(UserSession.user_id == current_user["user_id"]).first()
        state = get_project_elicitation_state(session, project_id)
        completed = bool(state.get("completed", False))
        return ElicitationStatus(
            history=state.get("history", []),
            current_question=None if completed else state.get("current_question", FIRST_QUESTION),
            summary=state.get("summary"),
            completed=completed,
            approved=bool(state.get("approved", False)),
        )
    finally:
        db.close()


@router.post("/{project_id}/elicitation/approve")
async def approve_elicitation(project_id: int, current_user: dict = Depends(get_current_user)):
    """La persona responsable valida el catálogo y habilita la siguiente fase."""
    db = SessionLocal()
    try:
        project = _require_project(db, current_user["user_id"], project_id)
        session = db.query(UserSession).filter(UserSession.user_id == current_user["user_id"]).first()
        state = get_project_elicitation_state(session, project_id)
        if not state.get("completed") or not state.get("summary"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Aún no hay un resumen de requerimientos para aprobar")
        state["approved"] = True
        save_project_elicitation_state(db, current_user["user_id"], project_id, state)
        project.phase_ready = True
        db.commit()
        return {"phase_ready": True, "message": "Requerimientos aprobados y fase lista para avanzar"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
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

    if body.project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La elicitación requiere un proyecto")

    db = SessionLocal()
    try:
        project = _require_project(db, user_id, body.project_id)
        session = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        elicitation_state = get_project_elicitation_state(session, body.project_id)
    finally:
        db.close()

    is_elicitation = project.current_phase == "requerimientos"
    if is_elicitation and elicitation_state.get("completed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La elicitación ya terminó; aprueba el resumen o crea una nueva sesión")

    # Build the LLM model (raises LLMConfigError if not configured)
    try:
        model = build_langchain_model(user_id)
    except LLMConfigError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM no configurado. Ejecuta POST /api/llm/config primero.",
        )

    async def event_generator():
        """Procesa una respuesta y emite la siguiente pregunta o el resumen."""
        try:
            if not is_elicitation:
                try:
                    docs, _metrics = await asyncio.to_thread(
                        similarity_search, query=body.message, user_id=user_id,
                        project_id=body.project_id, k=5, scope="all",
                    )
                    relevant_docs = [doc for doc in docs if _is_relevant(doc)]
                except Exception as exc:
                    logger.warning("RAG retrieval skipped for project_id=%s: %s", body.project_id, exc)
                    relevant_docs = []

                sources = [
                    {
                        "source_type": doc.metadata.get("source_type"),
                        "name": doc.metadata.get("pattern_name") or doc.metadata.get("filename"),
                        "similarity": doc.metadata.get("similarity"),
                    }
                    for doc in relevant_docs
                ]
                context = "\n\n".join(
                    f"[{index}] {doc.page_content}"
                    for index, doc in enumerate(relevant_docs, start=1)
                )
                prompt = (
                    "Eres un asistente de arquitectura de software. Responde en español, "
                    "de forma clara y accionable.\n\n"
                    f"Contexto recuperado desde RAG:\n{context or 'No se encontró contexto relevante.'}\n\n"
                    f"Mensaje del usuario: {body.message}"
                )
                yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"
                async for event in model.astream(prompt):
                    if event.content:
                        yield f"event: token\ndata: {json.dumps(event.content, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: null\n\n"
                return

            history = elicitation_state.get("history", [])
            question = elicitation_state.get("current_question", FIRST_QUESTION)
            history.append({"pregunta": question, "respuesta": body.message.strip()})
            decision = next_step(model, history, project.description or "")

            if decision.done:
                summary = generate_summary(model, history, project.description or "")
                elicitation_state.update({
                    "history": history, "current_question": None,
                    "summary": summary, "completed": True, "approved": False,
                })
                response = _summary_text(summary)
            else:
                elicitation_state.update({"history": history, "current_question": decision.question})
                response = decision.question or FIRST_QUESTION

            db = SessionLocal()
            try:
                save_project_elicitation_state(db, user_id, body.project_id, elicitation_state)
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

            yield f"event: token\ndata: {json.dumps(response, ensure_ascii=False)}\n\n"
            yield f"event: done\ndata: null\n\n"
        except ElicitationAgentError as exc:
            yield f"event: error\ndata: {json.dumps('No pude procesar la respuesta del modelo: ' + str(exc), ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps(str(e), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
