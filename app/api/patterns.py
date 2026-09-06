from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.pattern_document_storage import get_pattern_source_chunks
from app.models.architect_pattern import ArchitectPattern

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


class PatternOut(BaseModel):
    id: int
    pattern_name: str
    category: Optional[str]
    description: Optional[str]
    use_cases: Optional[str]
    tradeoffs: Optional[dict]
    when_not_to_use: Optional[str]

    class Config:
        from_attributes = True


class PatternListOut(BaseModel):
    total: int
    items: list[PatternOut]


class PatternSourceChunkOut(BaseModel):
    id: int
    chunk_type: str
    chunk_text: str
    chunk_metadata: Optional[dict]

    class Config:
        from_attributes = True


@router.get("", response_model=PatternListOut)
async def list_patterns(
    limit: int = Query(default=100, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """Lista de solo lectura del catalogo curado, paginada."""
    db = SessionLocal()
    try:
        base_query = db.query(ArchitectPattern).order_by(ArchitectPattern.pattern_name)
        total = base_query.count()
        items = base_query.offset(offset).limit(limit).all()
        return PatternListOut(total=total, items=items)
    finally:
        db.close()


@router.get("/{pattern_id}/source-chunks", response_model=list[PatternSourceChunkOut])
async def list_pattern_source_chunks(
    pattern_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Chunks subidos vía scripts/ingest_pattern_source.py (chunk_type="source_upload"),
    pendientes de curación manual. Solo lectura.
    """
    db = SessionLocal()
    try:
        exists = db.query(ArchitectPattern.id).filter(ArchitectPattern.id == pattern_id).first()
    finally:
        db.close()

    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patrón no encontrado")

    return get_pattern_source_chunks(pattern_id)