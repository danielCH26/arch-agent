from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
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


@router.get("", response_model=list[PatternOut])
async def list_patterns(current_user: dict = Depends(get_current_user)):
    """Lista de solo lectura del catalogo curado."""
    db = SessionLocal()
    try:
        return db.query(ArchitectPattern).order_by(ArchitectPattern.pattern_name).all()
    finally:
        db.close()
