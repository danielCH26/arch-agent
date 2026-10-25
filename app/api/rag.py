import asyncio
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.core.rag import MAX_QUERY_CHARS, RAGSearchError, similarity_search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


class RAGSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_CHARS)
    project_id: Optional[int] = None
    k: int = Field(default=5, ge=1, le=20)
    scope: Literal["all", "patterns", "documents"] = "all"
    category: Optional[str] = None


class RAGSearchResult(BaseModel):
    content: str
    metadata: dict[str, Any]


class RAGSearchResponse(BaseModel):
    """Respuesta pública de búsqueda.

    Solo expone ``search_ms`` (tramo de búsqueda vectorial). ``embedding_ms``,
    ``total_ms`` (= embedding + búsqueda) y ``embedding_cached`` NO se devuelven:
    la caché de embeddings es compartida entre usuarios y un ``embedding_ms``
    de 0 (o ``total_ms - search_ms``) revelaría que otro usuario ya consultó ese
    texto exacto. Esas métricas quedan en el log del servidor y en
    ``scripts/seed_bench_vectors.py``, que llama al core directamente.
    """

    results: list[RAGSearchResult]
    search_ms: float


def _build_response(results, metrics: dict[str, float]) -> RAGSearchResponse:
    logger.info(
        "rag search embedding_ms=%.2f search_ms=%.2f total_ms=%.2f embedding_cached=%s",
        metrics.get("embedding_ms", 0.0),
        metrics["search_ms"],
        metrics.get("total_ms", metrics["search_ms"]),
        metrics.get("embedding_cached"),
    )
    return RAGSearchResponse(
        results=[
            RAGSearchResult(content=doc.page_content, metadata=doc.metadata)
            for doc in results
        ],
        search_ms=round(metrics["search_ms"], 2),
    )


@router.post("/search", response_model=RAGSearchResponse)
async def search_rag(
    body: RAGSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Busca semanticamente en patrones y/o documentos subidos."""
    try:
        results, metrics = await asyncio.to_thread(
            similarity_search,
            query=body.query,
            user_id=current_user["user_id"],
            project_id=body.project_id,
            k=body.k,
            scope=body.scope,
            category=body.category,
        )
    except RAGSearchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _build_response(results, metrics)


@router.get("/patterns/search", response_model=RAGSearchResponse)
async def search_patterns(
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_CHARS),
    k: int = Query(default=5, ge=1, le=20),
    category: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    """Busca patrones de arquitectura relevantes."""
    try:
        results, metrics = await asyncio.to_thread(
            similarity_search,
            query=q,
            user_id=current_user["user_id"],
            k=k,
            scope="patterns",
            category=category,
        )
    except RAGSearchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _build_response(results, metrics)


@router.get("/documents/search", response_model=RAGSearchResponse)
async def search_documents(
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_CHARS),
    project_id: Optional[int] = Query(default=None),
    k: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """Busca chunks consultables de documentos del usuario autenticado."""
    try:
        results, metrics = await asyncio.to_thread(
            similarity_search,
            query=q,
            user_id=current_user["user_id"],
            project_id=project_id,
            k=k,
            scope="documents",
        )
    except RAGSearchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _build_response(results, metrics)
