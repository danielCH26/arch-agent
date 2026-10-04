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

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import threading
from time import perf_counter
from typing import Iterable, Literal, Optional

from langchain_core.documents import Document
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.embeddings import get_embeddings
from app.core.env import env_int
from app.models.architect_pattern import ArchitectPattern
from app.models.architect_pattern_chunk import ArchitectPatternChunk
from app.models.uploaded_document import DocumentChunk, UploadedDocument

SearchScope = Literal["all", "patterns", "documents"]

# La caché es por proceso y sólo contiene vectores de consultas; nunca guarda
# documentos ni resultados ligados a un usuario. Evita recalcular consultas
# frecuentes sin alterar autorización ni frescura de los resultados de DB.
_EMBEDDING_CACHE_SIZE = env_int("RAG_EMBEDDING_CACHE_SIZE", 512, minimum=0)
_embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
_embedding_cache_lock = threading.Lock()
_search_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-search")


class RAGSearchError(Exception):
    """Error especifico del pipeline RAG."""


def _validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != 384:
        raise RAGSearchError(f"Embedding invalido: se esperaban 384 dimensiones, llegaron {len(embedding)}")


def _similarity_from_cosine_distance(distance: float | None) -> float | None:
    if distance is None:
        return None
    return 1.0 - float(distance)


def _pattern_chunk_to_document(
    chunk: ArchitectPatternChunk,
    pattern: ArchitectPattern,
    distance: float | None,
) -> Document:
    metadata = {
        "source_type": "architect_pattern",
        "pattern_id": pattern.id,
        "pattern_name": pattern.pattern_name,
        "category": pattern.category,
        "tradeoffs": pattern.tradeoffs,
        "complexity": getattr(pattern, "complexity", None),
        "chunk_type": chunk.chunk_type,
        "distance": float(distance) if distance is not None else None,
        "similarity": _similarity_from_cosine_distance(distance),
    }
    return Document(page_content=chunk.chunk_text, metadata=metadata)


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


def clear_embedding_cache() -> None:
    """Vacía la caché de embeddings de consulta (útil para tests y operación)."""
    with _embedding_cache_lock:
        _embedding_cache.clear()


def _query_embedding(query: str) -> tuple[list[float], float, bool]:
    """Genera o recupera el embedding E5 de una consulta, con LRU thread-safe."""
    cache_key = f"query: {query}"
    if _EMBEDDING_CACHE_SIZE:
        with _embedding_cache_lock:
            cached = _embedding_cache.get(cache_key)
            if cached is not None:
                _embedding_cache.move_to_end(cache_key)
                return list(cached), 0.0, True

    started = perf_counter()
    embedding = get_embeddings().embed_query(cache_key)
    elapsed_ms = (perf_counter() - started) * 1000
    _validate_embedding(embedding)

    if _EMBEDDING_CACHE_SIZE:
        with _embedding_cache_lock:
            # Otro request puede haber terminado la misma consulta durante el
            # cálculo. Reusamos su vector y conservamos un LRU acotado.
            cached = _embedding_cache.get(cache_key)
            if cached is not None:
                _embedding_cache.move_to_end(cache_key)
                return list(cached), 0.0, True
            _embedding_cache[cache_key] = list(embedding)
            _embedding_cache.move_to_end(cache_key)
            while len(_embedding_cache) > _EMBEDDING_CACHE_SIZE:
                _embedding_cache.popitem(last=False)
    return list(embedding), elapsed_ms, False


def similarity_search_patterns_by_vector(
    query_embedding: list[float],
    k: int = 5,
    category: Optional[str] = None,
    probes: int = 10,
) -> tuple[list[Document], float]:
    """Busca chunks de patrones de arquitectura por similitud coseno en PGVector."""
    _validate_embedding(query_embedding)
    db = SessionLocal()
    started = perf_counter()
    try:
        _set_pgvector_probes(db, probes)
        distance = ArchitectPatternChunk.embedding.cosine_distance(query_embedding).label("distance")
        query = (
            db.query(ArchitectPatternChunk, ArchitectPattern, distance)
            .join(ArchitectPattern, ArchitectPattern.id == ArchitectPatternChunk.pattern_id)
            .filter(ArchitectPatternChunk.embedding.isnot(None))
        )
        if category:
            query = query.filter(ArchitectPattern.category == category)
        rows = query.order_by(distance).limit(k).all()
        elapsed_ms = (perf_counter() - started) * 1000
        return [_pattern_chunk_to_document(chunk, pattern, dist) for chunk, pattern, dist in rows], elapsed_ms
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
    query_embedding, embedding_ms, _ = _query_embedding(query)
    docs, search_ms = similarity_search_patterns_by_vector(query_embedding, k=k, category=category)
    return docs, search_ms, embedding_ms


def similarity_search_document_chunks(
    query: str,
    user_id: int,
    project_id: Optional[int] = None,
    k: int = 5,
) -> tuple[list[Document], float, float]:
    """Embebe una consulta y busca chunks privados relevantes."""
    query_embedding, embedding_ms, _ = _query_embedding(query)
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

    query_embedding, embedding_ms, embedding_cached = _query_embedding(query)

    groups: list[tuple[list[Document], float]] = []
    search_started = perf_counter()
    if scope == "all":
        # Cada función abre/cierra su propia sesión, por lo que estas lecturas
        # no comparten estado y pueden ejecutarse en paralelo de forma segura.
        pattern_future = _search_executor.submit(
            similarity_search_patterns_by_vector, query_embedding, k, category
        )
        document_future = _search_executor.submit(
            similarity_search_document_chunks_by_vector,
            query_embedding, int(user_id), project_id, k,
        )
        groups.extend((pattern_future.result(), document_future.result()))
    elif scope == "patterns":
        groups.append(similarity_search_patterns_by_vector(query_embedding, k=k, category=category))
    elif scope == "documents":
        groups.append(
            similarity_search_document_chunks_by_vector(
                query_embedding,
                user_id=int(user_id),
                project_id=project_id,
                k=k,
            )
        )

    merged = _merge_by_distance(groups)[:k]
    # Incluye encolado, ejecución y join de las ramas paralelas.
    search_ms = (perf_counter() - search_started) * 1000
    return merged, {
        "embedding_ms": embedding_ms,
        "search_ms": search_ms,
        "total_ms": embedding_ms + search_ms,
        "embedding_cached": embedding_cached,
    }
