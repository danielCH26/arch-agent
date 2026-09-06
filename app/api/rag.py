from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.core.rag import RAGSearchError, similarity_search

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RAGSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    project_id: Optional[int] = None
    k: int = Field(default=5, ge=1, le=20)
    scope: Literal["all", "patterns", "documents"] = "all"
    category: Optional[str] = None


class RAGSearchResult(BaseModel):
    content: str
    metadata: dict[str, Any]


class RAGSearchResponse(BaseModel):
    results: list[RAGSearchResult]
    search_ms: float
    embedding_ms: float
    total_ms: float


def _build_response(results, metrics: dict[str, float]) -> RAGSearchResponse:
    return RAGSearchResponse(
        results=[
            RAGSearchResult(content=doc.page_content, metadata=doc.metadata)
            for doc in results
        ],
        search_ms=round(metrics["search_ms"], 2),
        embedding_ms=round(metrics["embedding_ms"], 2),
        total_ms=round(metrics["total_ms"], 2),
    )


@router.post("/search", response_model=RAGSearchResponse)
async def search_rag(
    body: RAGSearchRequest,
    current_user: dict = Depends(get_current_user),
):
    """Busca semanticamente en patrones y/o documentos subidos."""
    try:
        results, metrics = similarity_search(
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
    q: str = Query(..., min_length=1),
    k: int = Query(default=5, ge=1, le=20),
    category: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    """Busca patrones de arquitectura relevantes."""
    try:
        results, metrics = similarity_search(
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
    q: str = Query(..., min_length=1),
    project_id: Optional[int] = Query(default=None),
    k: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
):
    """Busca chunks consultables de documentos del usuario autenticado."""
    try:
        results, metrics = similarity_search(
            query=q,
            user_id=current_user["user_id"],
            project_id=project_id,
            k=k,
            scope="documents",
        )
    except RAGSearchError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _build_response(results, metrics)
