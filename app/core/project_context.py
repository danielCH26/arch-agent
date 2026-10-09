"""Contexto adicional del proyecto para los prompts del LLM.

Dos fuentes que hasta ahora NO llegaban a la generación de la propuesta:

1. El resumen de requerimientos aprobado en la fase de elicitación
   (vive en ``sessions.engram_state[<project_id>]["requerimientos"]``).
2. El texto de los PDF/MD que el usuario subió al proyecto (actas de
   reunión, notas, etc.). Se leen de ``document_chunks`` completos, NO por
   búsqueda semántica: son contexto del proyecto (plazos, presupuesto,
   equipo...) y no algo que deba pasar un umbral de similitud para
   "merecer" entrar al prompt.

Todas las funciones son best-effort: si algo falla devuelven vacío y
loguean, para no romper la elicitación ni la generación de propuestas.
"""

from __future__ import annotations

import logging
import os

from app.core.database import SessionLocal
from app.core.env import env_int
from app.models.session import UserSession
from app.models.uploaded_document import DocumentChunk, UploadedDocument

logger = logging.getLogger(__name__)

# Tope total de caracteres de documentos que se inyectan en un prompt. Se
# puede ajustar por env: modelos con límite bajo de tokens por minuto (ej.
# Groq) fallan con 429 si el prompt crece demasiado.
DOCS_MAX_CHARS = env_int("PROJECT_DOCS_MAX_CHARS", 12000, minimum=0)

_REQ_PHASE = "requerimientos"


def _format_list(title: str, items) -> str:
    values = [str(i).strip() for i in (items or []) if str(i).strip()]
    if not values:
        return ""
    return f"{title}:\n" + "\n".join(f"- {v}" for v in values)


def format_requirements_summary(resumen: dict | None) -> str:
    """Convierte el ``resumen`` de elicitación en texto legible para un prompt."""
    if not isinstance(resumen, dict):
        return ""
    parts = []
    if resumen.get("problema"):
        parts.append(f"Problema: {resumen['problema']}")
    if resumen.get("usuarios"):
        parts.append(f"Usuarios: {resumen['usuarios']}")
    for key, title in (
        ("funcionalidades", "Funcionalidades"),
        ("restricciones", "Restricciones"),
        ("calidad", "Calidad"),
    ):
        block = _format_list(title, resumen.get(key))
        if block:
            parts.append(block)
    return "\n".join(parts)


def load_requirements_text(user_id: int, project_id: int) -> str:
    """Resumen de requerimientos vigente del proyecto ('' si no hay)."""
    db = None
    try:
        db = SessionLocal()
        row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        state = (row.engram_state if row is not None else None) or {}
        project_state = state.get(str(project_id), {})
        if not isinstance(project_state, dict):
            return ""
        phase_data = project_state.get(_REQ_PHASE, {})
        if not isinstance(phase_data, dict):
            return ""
        return format_requirements_summary(phase_data.get("resumen"))
    except Exception as exc:  # noqa: BLE001 -- best-effort
        logger.warning(
            "No se pudo leer el resumen de requerimientos user_id=%s project_id=%s: %s",
            user_id, project_id, exc,
        )
        return ""
    finally:
        if db is not None:
            db.close()


def load_documents_text(
    user_id: int,
    project_id: int,
    max_chars: int | None = None,
) -> tuple[str, list[str]]:
    """Texto de los documentos ya procesados del proyecto.

    Returns ``(texto, nombres_de_archivo)``. Los documentos van del más
    antiguo al más nuevo, cada uno con su encabezado, hasta ``max_chars``.
    Los que siguen con ``processed=False`` (embeddings en background) no
    tienen chunks todavía y se omiten.
    """
    limit = max_chars if max_chars is not None else DOCS_MAX_CHARS
    db = None
    try:
        db = SessionLocal()
        docs = (
            db.query(UploadedDocument)
            .filter(
                UploadedDocument.user_id == user_id,
                UploadedDocument.project_id == project_id,
                UploadedDocument.processed.is_(True),
            )
            .order_by(UploadedDocument.created_at.asc(), UploadedDocument.id.asc())
            .all()
        )
        blocks: list[str] = []
        names: list[str] = []
        used = 0
        for doc in docs:
            if used >= limit:
                break
            chunks = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index.asc())
                .all()
            )
            body = "\n".join((c.chunk_text or "").strip() for c in chunks).strip()
            if not body:
                continue
            header = f"### Documento: {doc.filename}\n"
            room = limit - used - len(header)
            if room <= 0:
                break
            if len(body) > room:
                body = body[:room].rstrip() + "\n[...recortado por tamaño...]"
            blocks.append(header + body)
            names.append(doc.filename)
            used += len(header) + len(body)
        return "\n\n".join(blocks), names
    except Exception as exc:  # noqa: BLE001 -- best-effort
        logger.warning(
            "No se pudieron leer los documentos user_id=%s project_id=%s: %s",
            user_id, project_id, exc,
        )
        return "", []
    finally:
        if db is not None:
            db.close()
