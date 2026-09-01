"""
Pipeline RAG sobre PGVector.

Expone busquedas semanticas para:
- architect_patterns: patrones publicos de arquitectura.
- document_chunks: chunks privados subidos por usuario/proyecto.

La integracion con LangChain se mantiene en dos puntos:
- get_embeddings() provee el Embeddings model usado para query/documents.
- Los resultados se retornan como langchain_core.documents.Document.
"""

from __future__ import annotations

from time import perf_counter
from typing import Iterable, Literal, Optional

from langchain_core.documents import Document
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.embeddings import get_embeddings
from app.models.architect_pattern import ArchitectPattern
from app.models.uploaded_document import DocumentChunk, UploadedDocument

SearchScope = Literal["all", "patterns", "documents"]


class RAGSearchError(Exception):
    """Error especifico del pipeline RAG."""


def _validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != 384:
        raise RAGSearchError(f"Embedding invalido: se esperaban 384 dimensiones, llegaron {len(embedding)}")


def _similarity_from_cosine_distance(distance: float | None) -> float | None:
    if distance is None:
        return None
    return 1.0 - float(distance)


def _pattern_to_document(pattern: ArchitectPattern, distance: float | None) -> Document:
    metadata = {
        "source_type": "architect_pattern",
        "pattern_id": pattern.id,
        "pattern_name": pattern.pattern_name,
        "category": pattern.category,
        "tradeoffs": pattern.tradeoffs,
        "distance": float(distance) if distance is not None else None,
        "similarity": _similarity_from_cosine_distance(distance),
    }
    page_content = "\n".join(
        part for part in [
            pattern.pattern_name,
            pattern.description,
            f"Casos de uso: {pattern.use_cases}" if pattern.use_cases else None,
        ] if part
    )
    return Document(page_content=page_content, metadata=metadata)


def _chunk_to_document(
    chunk: DocumentChunk,
    uploaded_document: UploadedDocument,
    distance: float | None,
) -> Document:
    metadata = {
        "source_type": "document_chunk",
        "chunk_id": chunk.id,
        "document_id": uploaded_document.id,
        "filename": uploaded_document.filename,
        "project_id": uploaded_document.project_id,
        "chunk_index": chunk.chunk_index,
        "distance": float(distance) if distance is not None else None,
        "similarity": _similarity_from_cosine_distance(distance),
    }
    if chunk.chunk_metadata:
        metadata.update(chunk.chunk_metadata)
    return Document(page_content=chunk.chunk_text or "", metadata=metadata)


def _set_pgvector_probes(db, probes: int) -> None:
    """Ajusta el recall de ivfflat para la transaccion actual."""
    db.execute(text(f"SET LOCAL ivfflat.probes = {int(probes)}"))


def similarity_search_patterns_by_vector(
    query_embedding: list[float],
    k: int = 5,
    category: Optional[str] = None,
    probes: int = 10,
) -> tuple[list[Document], float]:
    """Busca patrones de arquitectura por similitud coseno en PGVector."""
    _validate_embedding(query_embedding)
    db = SessionLocal()
    started = perf_counter()
    try:
        _set_pgvector_probes(db, probes)
        distance = ArchitectPattern.embedding.cosine_distance(query_embedding).label("distance")
        query = db.query(ArchitectPattern, distance).filter(ArchitectPattern.embedding.isnot(None))
        if category:
            query = query.filter(ArchitectPattern.category == category)
        rows = query.order_by(distance).limit(k).all()
        elapsed_ms = (perf_counter() - started) * 1000
        return [_pattern_to_document(pattern, dist) for pattern, dist in rows], elapsed_ms
    finally:
        db.close()


def similarity_search_document_chunks_by_vector(
    query_embedding: list[float],
    user_id: int,
    project_id: Optional[int] = None,
    k: int = 5,
    probes: int = 10,
) -> tuple[list[Document], float]:
    """Busca chunks de documentos respetando ownership por usuario y proyecto."""
    _validate_embedding(query_embedding)
    db = SessionLocal()
    started = perf_counter()
    try:
        _set_pgvector_probes(db, probes)
        distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
        query = (
            db.query(DocumentChunk, UploadedDocument, distance)
            .join(UploadedDocument, UploadedDocument.id == DocumentChunk.document_id)
            .filter(
                UploadedDocument.user_id == user_id,
                UploadedDocument.processed.is_(True),
                DocumentChunk.embedding.isnot(None),
            )
        )
        if project_id is not None:
            query = query.filter(UploadedDocument.project_id == project_id)
        rows = query.order_by(distance).limit(k).all()
        elapsed_ms = (perf_counter() - started) * 1000
        return [_chunk_to_document(chunk, doc, dist) for chunk, doc, dist in rows], elapsed_ms
    finally:
        db.close()


def similarity_search_patterns(
    query: str,
    k: int = 5,
    category: Optional[str] = None,
) -> tuple[list[Document], float, float]:
    """Embebe una consulta y busca patrones relevantes."""
    embed_started = perf_counter()
    query_embedding = get_embeddings().embed_query(query)
    embedding_ms = (perf_counter() - embed_started) * 1000
    docs, search_ms = similarity_search_patterns_by_vector(query_embedding, k=k, category=category)
    return docs, search_ms, embedding_ms


def similarity_search_document_chunks(
    query: str,
    user_id: int,
    project_id: Optional[int] = None,
    k: int = 5,
) -> tuple[list[Document], float, float]:
    """Embebe una consulta y busca chunks privados relevantes."""
    embed_started = perf_counter()
    query_embedding = get_embeddings().embed_query(query)
    embedding_ms = (perf_counter() - embed_started) * 1000
    docs, search_ms = similarity_search_document_chunks_by_vector(
        query_embedding,
        user_id=user_id,
        project_id=project_id,
        k=k,
    )
    return docs, search_ms, embedding_ms


def _merge_by_distance(result_groups: Iterable[tuple[list[Document], float]]) -> list[Document]:
    docs: list[Document] = []
    for group, _ in result_groups:
        docs.extend(group)
    return sorted(
        docs,
        key=lambda doc: doc.metadata["distance"] if doc.metadata.get("distance") is not None else 999.0,
    )


def similarity_search(
    query: str,
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
    k: int = 5,
    scope: SearchScope = "all",
    category: Optional[str] = None,
) -> tuple[list[Document], dict[str, float]]:
    """
    Busca en patrones y/o documentos con una sola interfaz.

    Returns:
        (documents, metrics) donde metrics separa embedding_ms y search_ms.
        search_ms mide solo consultas PGVector; es el numero relevante para
        validar el criterio <100ms con 10k vectores.
    """
    if scope not in {"all", "patterns", "documents"}:
        raise RAGSearchError("scope debe ser 'all', 'patterns' o 'documents'")
    if scope in {"all", "documents"} and user_id is None:
        raise RAGSearchError("user_id es requerido para buscar documentos")

    embed_started = perf_counter()
    query_embedding = get_embeddings().embed_query(query)
    embedding_ms = (perf_counter() - embed_started) * 1000

    groups: list[tuple[list[Document], float]] = []
    if scope in {"all", "patterns"}:
        groups.append(similarity_search_patterns_by_vector(query_embedding, k=k, category=category))
    if scope in {"all", "documents"}:
        groups.append(
            similarity_search_document_chunks_by_vector(
                query_embedding,
                user_id=int(user_id),
                project_id=project_id,
                k=k,
            )
        )

    merged = _merge_by_distance(groups)[:k]
    search_ms = sum(group_ms for _, group_ms in groups)
    return merged, {
        "embedding_ms": embedding_ms,
        "search_ms": search_ms,
        "total_ms": embedding_ms + search_ms,
    }
