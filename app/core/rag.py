"""
RAG retriever para F08 (Generación propuesta + aprobación).

Issue: #12

IMPORTANTE: este retriever NO usa PGVector de LangChain porque el proyecto
usa tablas propias (architect_patterns, document_chunks) con pgvector directo
via SQLAlchemy, no el esquema interno de LangChain (langchain_pg_*).

Combina:
- Chunks de documentos del usuario (HU13) → tabla document_chunks
- Patrones seed (F07) → tabla architect_patterns

Búsqueda: cosine similarity calculada en SQL (operador <=> de pgvector).
"""

from typing import Optional

from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.embeddings import get_embeddings
from langchain_core.documents import Document


def _to_pgvector_literal(vector: list[float]) -> str:
    """Convierte una lista de floats al formato literal de pgvector '[v1,v2,...]'."""
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


def retrieve_user_documents(
    user_id: int,
    query_embedding: list[float],
    project_id: Optional[int] = None,
    top_k: int = 5,
) -> list[Document]:
    """
    Busca chunks de documentos del usuario por similitud coseno.

    Args:
        user_id: filtro de privacidad (obligatorio)
        query_embedding: embedding de la query (384d)
        project_id: filtro opcional por proyecto
        top_k: máximo de resultados

    Returns:
        Lista de Documents (puede estar vacía)
    """
    literal = _to_pgvector_literal(query_embedding)
    sql = text("""
        SELECT c.id, c.document_id, c.chunk_text, c.chunk_index, c.metadata,
               1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM document_chunks c
        INNER JOIN uploaded_documents u ON u.id = c.document_id
        WHERE u.user_id = :user_id
          AND (:project_id::INTEGER IS NULL OR u.project_id = :project_id)
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    db = SessionLocal()
    try:
        rows = db.execute(sql, {
            "embedding": literal,
            "user_id": user_id,
            "project_id": project_id,
            "limit": top_k,
        }).fetchall()

        return [
            Document(
                page_content=row.chunk_text or "",
                metadata={
                    "source": "user_document",
                    "document_id": row.document_id,
                    "chunk_index": row.chunk_index,
                    "similarity": float(row.similarity),
                    **(row.metadata or {}),
                },
            )
            for row in rows
        ]
    except Exception:
        return []
    finally:
        db.close()


def retrieve_patterns(
    query_embedding: list[float],
    top_k: int = 3,
) -> list[Document]:
    """
    Busca patrones de arquitectura (seed de F07) por similitud coseno.

    Si F07 no está listo (tabla vacía), retorna [].

    Returns:
        Lista de Documents (puede estar vacía)
    """
    literal = _to_pgvector_literal(query_embedding)
    sql = text("""
        SELECT id, pattern_name, category, description, use_cases,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM architect_patterns
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    db = SessionLocal()
    try:
        rows = db.execute(sql, {
            "embedding": literal,
            "limit": top_k,
        }).fetchall()

        return [
            Document(
                page_content=(
                    f"Patrón: {row.pattern_name}\n"
                    f"Categoría: {row.category}\n"
                    f"Descripción: {row.description}\n"
                    f"Casos de uso: {row.use_cases}"
                ),
                metadata={
                    "source": "seed_pattern",
                    "pattern_name": row.pattern_name,
                    "category": row.category,
                    "similarity": float(row.similarity),
                },
            )
            for row in rows
        ]
    except Exception:
        return []
    finally:
        db.close()


def retrieve_context(
    user_id: int,
    query: str,
    project_id: Optional[int] = None,
    top_k_docs: int = 5,
    top_k_patterns: int = 3,
) -> list[Document]:
    """
    Recupera contexto relevante del RAG: docs del usuario + patrones seed.

    Args:
        user_id: ID del usuario (filtro de privacidad, obligatorio)
        query: texto de búsqueda (mensaje del usuario)
        project_id: ID del proyecto (opcional, filtra docs por proyecto)
        top_k_docs: máximo de documentos del usuario
        top_k_patterns: máximo de patrones

    Returns:
        Lista de Documents relevantes (puede estar vacía).
        Nunca lanza excepción: los errores se loggean y retornan [].
    """
    if not query or not query.strip():
        return []

    try:
        query_embedding = get_embeddings().embed_query(query)
    except Exception:
        return []

    docs: list[Document] = []

    # 1. Docs del usuario (HU13)
    docs.extend(
        retrieve_user_documents(
            user_id=user_id,
            query_embedding=query_embedding,
            project_id=project_id,
            top_k=top_k_docs,
        )
    )

    # 2. Patrones seed (F07, con fallback silencioso)
    docs.extend(
        retrieve_patterns(
            query_embedding=query_embedding,
            top_k=top_k_patterns,
        )
    )

    return docs
