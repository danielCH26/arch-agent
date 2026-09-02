import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.api.sse import SSEStreamCallbackHandler
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.database import SessionLocal
from app.core.rag import similarity_search
from app.models.project import Project

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)


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
        200 text/event-stream — "sources" event (metadata RAG) + tokens
            como "event: token" + final "event: done"
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

        context_blocks = []
        for index, doc in enumerate(docs, start=1):
            source = doc.metadata.get("pattern_name") or doc.metadata.get("filename") or doc.metadata.get("source_type")
            context_blocks.append(f"[{index}] {source}\n{doc.page_content}")
        return docs, "\n\n".join(context_blocks)

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
            async for event in model.astream(prompt):
                if event.content:
                    # Yield the token as SSE
                    yield f"event: token\ndata: {json.dumps(event.content, ensure_ascii=False)}\n\n"
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