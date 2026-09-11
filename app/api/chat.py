import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.llm_loader import LLMConfigError, build_langchain_model
from app.core.rag import similarity_search
from app.models.project import Project

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)
RAG_MIN_SIMILARITY = 0.85


class ChatRequest(BaseModel):
    project_id: int | None = None
    message: str


def _require_project(db, user_id: int, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if project is not None:
        return project
    exists = db.query(Project).filter(Project.id == project_id).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")


@router.post("")
async def chat(body: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Chat RAG genérico; la elicitación guiada vive en /api/projects/*/elicitation."""
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mensaje vacío")

    user_id = current_user["user_id"]
    if body.project_id is not None:
        db = SessionLocal()
        try:
            _require_project(db, user_id, body.project_id)
        finally:
            db.close()

    try:
        model = build_langchain_model(user_id)
    except LLMConfigError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="LLM no configurado. Ejecuta POST /api/llm/config primero.")

    async def event_generator():
        try:
            try:
                docs, _metrics = await asyncio.to_thread(
                    similarity_search, query=body.message, user_id=user_id,
                    project_id=body.project_id, k=5, scope="all",
                )
                relevant_docs = [doc for doc in docs if (doc.metadata.get("similarity") or 0.0) >= RAG_MIN_SIMILARITY]
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
            context = "\n\n".join(f"[{index}] {doc.page_content}" for index, doc in enumerate(relevant_docs, start=1))
            prompt = (
                "Eres un asistente de arquitectura de software. Responde en español, de forma clara y accionable.\n\n"
                f"Contexto recuperado desde RAG:\n{context or 'No se encontró contexto relevante.'}\n\n"
                f"Mensaje del usuario: {body.message}"
            )
            yield f"event: sources\ndata: {json.dumps(sources, ensure_ascii=False)}\n\n"
            async for event in model.astream(prompt):
                if event.content:
                    yield f"event: token\ndata: {json.dumps(event.content, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: null\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps(str(exc), ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
