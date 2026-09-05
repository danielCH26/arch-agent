from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP, func
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class ArchitectPatternChunk(Base):
    """Chunk indexado de un patron de arquitectura."""

    __tablename__ = "architect_pattern_chunks"

    id = Column(Integer, primary_key=True)
    pattern_id = Column(Integer, ForeignKey("architect_patterns.id", ondelete="CASCADE"), nullable=False)
    chunk_type = Column(String(50), nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(384))
    created_at = Column(TIMESTAMP, server_default=func.now())
