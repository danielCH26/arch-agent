import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.api.sse import SSEStreamCallbackHandler, format_done_event
from app.core.agent import run_agent
from app.core.langfuse_tracer import get_langfuse_handler
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.database import SessionLocal
from app.core.rag import similarity_search
from app.models.project import Project

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
        200 text/event-stream — "sources" event (metadata RAG) +
            ("tool_start" / "tool_end")* + tokens as "event: token" +
            optional "event: degraded" + final "event: done".
            On hard failure, "event: error" terminates the stream.
        400 — no message provided
        401 — invalid JWT
        404 — project not found or not owned
        409 — LLM not configured for user

    F11 changes (issue #13, design.md §6.5):
      - swaps ``model.astream(prompt)`` for ``run_agent(model, message,
        callbacks=..., rag_documents=...)`` which drives a
        ``create_agent`` runtime.
      - The route owns RAG retrieval (unchanged) and emits ``sources``
        before invoking ``run_agent`` so the FE gets a stable ordering.
      - ``run_agent`` may emit ``tool_start`` / ``tool_end`` pairs and,
        on Context7 unavailability, exactly one ``degraded`` event
        (REQ-6). Tokens and ``done`` come from ``run_agent``.
      - The SSE handler (``SSEStreamCallbackHandler``) remains the source
        of truth for tool event bytes (F11.4a).
      - The optional Langfuse handler (``get_langfuse_handler``) is
        appended to the callback list when env vars are present, else
        skipped (REQ-5 / SCN-6).
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

    # Build SSE streaming handler + optional Langfuse callback
    handler = SSEStreamCallbackHandler()
    langfuse_handler = get_langfuse_handler()
    callbacks: list = [handler]
    if langfuse_handler is not None:
        callbacks.append(langfuse_handler)

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
        SSE generator that yields events as they arrive from the agent runtime.

        Ordering (design.md §5.2):
          sources -> (tool_start/tool_end)* -> token*N -> done

        ``sources`` is emitted by this route BEFORE the agent runs (the agent
        reuses the pre-fetched ``relevant_docs`` for system-prompt injection).
        ``run_agent`` may also emit exactly one ``degraded`` event between
        ``sources`` and the first ``token`` (REQ-6 / SCN-3); the route logs
        a WARNING when that happens but lets the stream continue.
        """
        try:
            docs, rag_context = await retrieve_context()

            sources = [_doc_to_source(doc) for doc in docs]
            yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"

            emitted_done = False
            async for sse_dict in run_agent(
                model=model,
                message=body.message,
                callbacks=callbacks,
                rag_documents=docs,
                user_id=user_id,
                project_id=body.project_id,
            ):
                event_name = sse_dict.get("event")
                payload = sse_dict.get("data")

                if event_name == "degraded":
                    logger.warning(
                        "Context7 unavailable for user_id=%s project_id=%s; "
                        "falling back to RAG-only: %s",
                        user_id,
                        body.project_id,
                        payload,
                    )
                    yield f"event: degraded\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue

                if event_name == "error":
                    yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    emitted_done = True  # error is terminal
                    break

                if event_name == "done":
                    yield format_done_event()
                    emitted_done = True
                    continue

                if event_name == "token":
                    yield f"event: token\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue

                if event_name == "tool_start":
                    yield f"event: tool_start\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue

                if event_name == "tool_end":
                    yield f"event: tool_end\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    continue

                # Unknown event types are ignored on purpose (forward-compat
                # for future F12+ events).
                continue

            if not emitted_done:
                # Defensive: if ``run_agent`` returned without yielding
                # ``done`` or ``error``, fire ``done`` to keep the FE
                # contract stable (design.md §9).
                yield format_done_event()
        except Exception as e:
            logger.exception("event_generator failed: %s", e)
            yield f"event: error\ndata: {json.dumps(str(e), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
