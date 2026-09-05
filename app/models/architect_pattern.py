from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class ArchitectPattern(Base):
    """Patron de arquitectura indexado para busqueda semantica."""

    __tablename__ = "architect_patterns"

    id = Column(Integer, primary_key=True)
    pattern_name = Column(String(255), nullable=False)
    category = Column(String(100))
    description = Column(Text)
    use_cases = Column(Text)
    tradeoffs = Column(JSONB)
    when_not_to_use = Column(Text)
    decision_signals = Column(JSONB)
    embedding = Column(Vector(384))
    created_at = Column(TIMESTAMP, server_default=func.now())
