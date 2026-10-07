"""
Pipeline RAG sobre PGVector.

Expone busquedas semanticas para:
- architect_patterns: patrones publicos de arquitectura.
- document_chunks: chunks privados subidos por usuario/proyecto.

La integracion con LangChain se mantiene en dos puntos:
- get_embeddings() provee el Embeddings model usado para query/documents.
- Los resultados se retornan como langchain_core.documents.Document.

Metricas (F19), todas en milisegundos:
- embedding_ms: tiempo de embeber la consulta; 0 en un cache hit.
- search_ms: tiempo de pared de TODA la etapa de busqueda. Con scope="all"
  incluye encolado en el executor, la ejecucion de las dos ramas (en paralelo)
  y el join, asi que ronda la rama mas lenta y no la suma. Con un solo scope es
  la consulta PGVector de esa tabla.
- total_ms: embedding_ms + search_ms.
Las cifras anteriores a F19 (docs/QA_criterios_aceptacion_RAG_final.md, una sola
tabla y sin executor) no son comparables 1:1 con search_ms de scope="all".
"""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from time import perf_counter
from typing import Iterable, Literal, Optional

from langchain_core.documents import Document
from sqlalchemy import text

from app.core.database import DB_MAX_OVERFLOW, DB_POOL_SIZE, SessionLocal
from app.core.embeddings import get_embeddings
from app.core.env import env_int
from app.models.architect_pattern import ArchitectPattern
from app.models.architect_pattern_chunk import ArchitectPatternChunk
from app.models.uploaded_document import DocumentChunk, UploadedDocument

logger = logging.getLogger(__name__)

SearchScope = Literal["all", "patterns", "documents"]

# La caché es por proceso y sólo contiene vectores de consultas; nunca guarda
# documentos ni resultados ligados a un usuario. Evita recalcular consultas
# frecuentes sin alterar autorización ni frescura de los resultados de DB.
_EMBEDDING_CACHE_SIZE = env_int("RAG_EMBEDDING_CACHE_SIZE", 512, minimum=0)
_embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
_embedding_cache_lock = threading.Lock()
# Executor compartido por todas las requests: cada busqueda scope=all usa 2 hilos,
# asi que con pocos workers las requests concurrentes se encolan entre si. El
# default (16) queda por debajo de DB_POOL_SIZE + DB_MAX_OVERFLOW (30).
_SEARCH_WORKERS = env_int("RAG_SEARCH_WORKERS", 16, minimum=2)


def _warn_if_workers_exceed_pool(workers: int, pool_size: int, max_overflow: int) -> bool:
    """Avisa (sin bloquear el arranque) si hay mas hilos de busqueda que conexiones.

    Cada rama de ``scope=all`` abre su propia sesion: con mas workers que
    conexiones posibles (``pool_size + max_overflow``) los hilos sobrantes
    esperan ``DB_POOL_TIMEOUT`` y fallan con ``TimeoutError`` bajo carga.
    Devuelve True si emitio el warning.

    OJO: esta comprobacion solo cubre los hilos de RAG. El executor por defecto
    de ``asyncio.to_thread`` (carga de contexto, guardado de propuestas, etc.)
    tambien abre sesiones del mismo pool, y el pool es POR PROCESO: la formula
    completa esta en ``.env.example``.
    """
    capacity = pool_size + max_overflow
    if workers <= capacity:
        return False
    logger.warning(
        "RAG_SEARCH_WORKERS=%d supera DB_POOL_SIZE + DB_MAX_OVERFLOW=%d; bajo carga "
        "los hilos de busqueda pueden agotar el pool (timeout). Reduce RAG_SEARCH_WORKERS "
        "o sube el pool (y recuerda que asyncio.to_thread tambien usa conexiones).",
        workers,
        capacity,
    )
    return True


_warn_if_workers_exceed_pool(_SEARCH_WORKERS, DB_POOL_SIZE, DB_MAX_OVERFLOW)
_search_executor = ThreadPoolExecutor(
    max_workers=_SEARCH_WORKERS, thread_name_prefix="rag-search"
)


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
    """Genera o recupera el embedding E5 de una consulta, con LRU thread-safe.

    Devuelve ``(embedding, embedding_ms, cached)``. La clave es el texto exacto de
    la consulta (con el prefijo ``query: `` de E5): no se normaliza mayusculas ni
    espacios. Con ``RAG_EMBEDDING_CACHE_SIZE=0`` la cache esta desactivada.

    La cache es por proceso y compartida entre usuarios: solo guarda vectores
    (nunca resultados ni datos de usuarios), pero un ``embedding_ms == 0``
    delata que ese mismo texto ya se consulto antes en este proceso. Por eso la
    API publica (``app/api/rag.py``) no devuelve ``embedding_ms``, ``total_ms`` ni
    ``embedding_cached``; solo los usan el log del servidor y el benchmark. Queda
    un canal lateral por latencia total de la peticion, mucho mas ruidoso; si el
    modelo de amenaza lo exige, incluir ``user_id`` en la clave.

    Si dos hilos calculan a la vez la misma consulta nueva, ambos gastan el
    embedding; el que termina segundo reutiliza el vector ya guardado y devuelve
    ``(vector, 0.0, True)`` aunque su tiempo real no fue 0. Es una subestimacion
    acotada de ``embedding_ms`` solo en esa carrera.
    """
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
        (documents, metrics) con ``embedding_ms``, ``search_ms``, ``total_ms`` y
        ``embedding_cached``. ``search_ms`` es el tiempo de pared de toda la etapa
        de busqueda (encolado + ejecucion + join de las ramas paralelas con
        scope="all"); es el numero que se compara con el criterio < 100 ms con
        10k vectores por tabla. ``embedding_ms`` queda fuera de ``search_ms``.
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
