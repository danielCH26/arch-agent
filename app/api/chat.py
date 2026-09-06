import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_current_user
from app.api.sse import SSEStreamCallbackHandler
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.database import SessionLocal
from app.core.message_store import ensure_user_session, engram_mirror, list_recent, save_message
from app.core.rag import similarity_search
from app.models.project import Project
from app.models.session import UserSession

# Umbral MINIMO de similitud para considerar un chunk/patron "relevante".
# Sin esto, similarity_search() siempre devuelve los top-k mas cercanos
# aunque ninguno tenga relacion real con la query.
#
# Es un UNICO umbral global (no diferenciado por tipo) -- se intento
# diferenciar por source_type (patrones vs. documentos) pero la evidencia
# real termino contradiciendolo: un falso positivo de un documento
# (PDF de matematicas, en una pregunta de microservicios) salio a 83%,
# por ENCIMA de un verdadero positivo de otro documento real (PDF de
# grafos/MapReduce, en su propia pregunta, a 80-81%). Con este modelo de
# embeddings (multilingual-e5-small), la similitud coseno sola no separa
# limpiamente relevante/irrelevante en la banda 80-88%; no existe un
# numero (global o por tipo) que acierte siempre en esa zona gris.
#
# 0.85 es un punto intermedio elegido con la evidencia acumulada:
#   Verdaderos positivos medidos: 88% (patron), 89-92% (documento).
#   Falsos positivos medidos:     75-78%, 81-83% (ambos tipos).
# Es una heuristica "best effort", no una garantia -- puede ocasionalmente
# dejar pasar ruido cerca del limite, o descartar un match debil pero
# legitimo. Si se necesita precision real en esa zona gris, la solucion
# correcta es un paso de re-ranking (ej. que el LLM juzgue relevancia
# real de cada candidato, o un cross-encoder), no seguir ajustando este
# numero -- quedo fuera del alcance de esta HU, ver docs/QA_criterios_aceptacion_RAG.md.
RAG_MIN_SIMILARITY = 0.85

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _is_relevant(doc) -> bool:
    return (doc.metadata.get("similarity") or 0.0) >= RAG_MIN_SIMILARITY


# --- Request model ---------------------------------------------------------

class ChatRequest(BaseModel):
    project_id: int | None = None
    message: str


# --- Routes ----------------------------------------------------------------

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
        200 text/event-stream — "sources" event (metadata RAG) + tokens
            como "event: token" + final "event: done"
        400 — no message provided
        401 — invalid JWT
        404 — project not found or not owned
        409 — LLM not configured for user
        503 — Postgres unreachable (REQ-11)

    Behaviour change (F12, REQ-4 / REQ-6): each turn inserts a Message(role=user)
    + Message(role=assistant) row in ONE Postgres transaction that commits BEFORE
    the SSE handler yields ``event: done``; fire-and-forget Engram mirror fires
    AFTER the commit. Either store degrades gracefully when the other is down.
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

    # Build the LLM model (raises LLMConfigError if not configured)
    try:
        model = build_langchain_model(user_id)
    except LLMConfigError as e:
        if e.reason == "initialization_failed":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM no configurado. Ejecuta POST /api/llm/config primero.",
        )

    # Build SSE streaming handler
    handler = SSEStreamCallbackHandler()

    async def retrieve_context() -> tuple[list, str]:
        try:
            docs, _metrics = await asyncio.to_thread(
                similarity_search,
                query=body.message,
                user_id=user_id,
                project_id=body.project_id,
                k=5,
                scope="all",
            )
        except Exception as e:
            logger.warning("RAG retrieval skipped for user_id=%s project_id=%s: %s", user_id, body.project_id, e)
            return [], ""

        # Descarta lo que quedo por debajo del umbral de relevancia -- ver
        # comentario junto a RAG_MIN_SIMILARITY.
        relevant_docs = [doc for doc in docs if _is_relevant(doc)]

        context_blocks = []
        for index, doc in enumerate(relevant_docs, start=1):
            source = doc.metadata.get("pattern_name") or doc.metadata.get("filename") or doc.metadata.get("source_type")
            context_blocks.append(f"[{index}] {source}\n{doc.page_content}")
        return relevant_docs, "\n\n".join(context_blocks)

    def _doc_to_source(doc) -> dict:
        """Metadata minima para que el frontend pueda mostrar/loguear que fuente se uso."""
        return {
            "source_type": doc.metadata.get("source_type"),
            "name": doc.metadata.get("pattern_name") or doc.metadata.get("filename"),
            "similarity": doc.metadata.get("similarity"),
        }

    async def event_generator():
        """
        SSE generator that yields tokens as they arrive from the model.

        Recupera contexto RAG desde PGVector y lo agrega al prompt.
        Antes de los tokens, emite un evento 'sources' con la metadata de
        los documentos recuperados (o [] si no hubo match / hubo error),
        asi el frontend puede mostrar/loguear si la respuesta se apoyo
        realmente en la base vectorial.

        F12 (REQ-4, REQ-6): after the last token, persists both Message rows
        (user + assistant) in ONE Postgres transaction BEFORE yielding
        ``event: done``; then fires-and-forgets the Engram mirror.
        """
        try:
            docs, rag_context = await retrieve_context()

            sources = [_doc_to_source(doc) for doc in docs]
            yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"

            prompt = (
                "Eres un asistente de arquitectura de software. "
                "Responde en español, de forma clara y accionable.\n\n"
                "Formato: usa markdown (encabezados, negritas, tablas) libremente, "
                "pero NUNCA envuelvas la respuesta completa dentro de un bloque de "
                "codigo (```). Usa ``` unicamente para fragmentos de codigo real o "
                "diagramas ASCII puntuales, nunca para el mensaje entero.\n\n"
                "Contexto recuperado desde RAG:\n"
                f"{rag_context or 'No se encontro contexto relevante.'}\n\n"
                f"Mensaje del usuario: {body.message}"
            )

            full_response = ""
            async for event in model.astream(prompt):
                if event.content:
                    full_response += event.content
                    yield f"event: token\ndata: {json.dumps(event.content, ensure_ascii=False)}\n\n"

            # Persist both rows in ONE Postgres tx BEFORE yield done (REQ-4).
            # If Postgres is unreachable we return 503 per REQ-11; the SSE
            # stream never emits 'done' so the client knows the turn failed.
            try:
                db = SessionLocal()
                try:
                    session_id = ensure_user_session(db, user_id)
                    user_msg = save_message(
                        db,
                        session_id=session_id,
                        project_id=body.project_id,
                        user_id=user_id,
                        role="user",
                        content=body.message,
                    )
                    asst_msg = save_message(
                        db,
                        session_id=session_id,
                        project_id=body.project_id,
                        user_id=user_id,
                        role="assistant",
                        content=full_response,
                        citations=sources,
                    )
                    db.commit()

                    # Fire-and-forget Engram mirror AFTER the commit (REQ-6,
                    # REQ-10). Failures are logged inside engram_mirror and
                    # never raised back to the SSE stream.
                    engram_mirror(user_msg, user_id=user_id, project_id=body.project_id)
                    engram_mirror(asst_msg, user_id=user_id, project_id=body.project_id)
                finally:
                    db.close()
            except SQLAlchemyError as exc:
                logger.error(
                    "messages insert failed user_id=%s project_id=%s: %s",
                    user_id,
                    body.project_id,
                    exc,
                )
                yield f"event: error\ndata: {json.dumps('messages store unavailable', ensure_ascii=False)}\n\n"
                return

            yield f"event: done\ndata: null\n\n"
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


@router.get("/history")
def chat_history(
    project_id: int = Query(..., ge=1),
    limit: int = Query(5, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """
    GET /api/chat/history?project_id=<int>&limit=<int:1..50,default=5>

    Returns the last ``limit`` messages for ``(user_id, project_id)`` ordered
    newest-first. Cross-user access returns 404 (REQ-7, do not leak existence).
    Postgres unreachable returns 200 ``{"messages": []}`` per REQ-11 / SCN-5.
    """
    user_id = current_user["user_id"]
    # FastAPI already clamps via Query(ge=1, le=50); defensive clamp too.
    limit = max(1, min(50, int(limit)))

    db = SessionLocal()
    try:
        # Ownership check: 404 cross-user (REQ-7). Do NOT leak existence.
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

        # Resolve the user's session id (lazy-upsert so a fresh user still
        # gets an empty list, not an exception). REQ-11: any DB failure on
        # the read path → 200 with empty messages (graceful degradation).
        try:
            session = (
                db.query(UserSession).filter(UserSession.user_id == user_id).first()
            )
            if session is None:
                return {"messages": []}

            rows = list_recent(db, session.id, limit=limit)
        except SQLAlchemyError as exc:
            logger.warning(
                "history read skipped, Postgres unreachable user_id=%s: %s",
                user_id,
                exc,
            )
            return {"messages": []}

        return {
            "messages": [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "citations": row.citations or [],
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        }
    finally:
        db.close()