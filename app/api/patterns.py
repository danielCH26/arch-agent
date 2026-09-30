from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.pattern_document_storage import get_pattern_source_chunks
from app.core.pattern_justification import CURATED_SOURCE_LABEL
from app.models.architect_pattern import ArchitectPattern
from app.models.architect_pattern_chunk import ArchitectPatternChunk

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


class PatternChunkOut(BaseModel):
    id: int
    chunk_type: str
    chunk_text: str
    source: str


class PatternDetailOut(PatternOut):
    decision_signals: Optional[list]
    chunks: list[PatternChunkOut]


@router.get("/{pattern_id}", response_model=PatternDetailOut)
async def get_pattern(
    pattern_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Detalle de un patrón con todos los chunks indexados en el RAG (HU8).

    Es el destino de ``verify_url`` en las citas de una propuesta: permite al
    usuario leer el texto completo que respaldó cada decisión y de qué fuente
    proviene (catálogo curado o documento subido).
    """
    db = SessionLocal()
    try:
        pattern = db.query(ArchitectPattern).filter(ArchitectPattern.id == pattern_id).first()
        if pattern is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patrón no encontrado")

        chunks = (
            db.query(ArchitectPatternChunk)
            .filter(ArchitectPatternChunk.pattern_id == pattern_id)
            .order_by(ArchitectPatternChunk.id)
            .all()
        )
        return PatternDetailOut(
            id=pattern.id,
            pattern_name=pattern.pattern_name,
            category=pattern.category,
            description=pattern.description,
            use_cases=pattern.use_cases,
            tradeoffs=pattern.tradeoffs,
            when_not_to_use=pattern.when_not_to_use,
            decision_signals=pattern.decision_signals,
            chunks=[
                PatternChunkOut(
                    id=chunk.id,
                    chunk_type=chunk.chunk_type,
                    chunk_text=chunk.chunk_text,
                    source=(chunk.chunk_metadata or {}).get("filename")
                    or CURATED_SOURCE_LABEL,
                )
                for chunk in chunks
            ],
        )
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