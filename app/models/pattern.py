from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class ArchitectPattern(Base):
    """Patrón de arquitectura consultable por el agente vía RAG (HU5, HU6, HU7)."""

    __tablename__ = "architect_patterns"

    id = Column(Integer, primary_key=True)
    pattern_name = Column(String(255), nullable=False)
    category = Column(String(100))
    description = Column(Text)
    use_cases = Column(Text)
    tradeoffs = Column(JSONB)  # {"ventajas": [...], "desventajas": [...]}
    embedding = Column(Vector(384))  # multilingual-e5-small produce 384d
    created_at = Column(TIMESTAMP, server_default=func.now())
