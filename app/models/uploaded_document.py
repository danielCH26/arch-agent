from sqlalchemy import (
    Column, Integer, String, Text, Boolean, TIMESTAMP, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.core.database import Base


class UploadedDocument(Base):
    """Documento subido por un usuario al RAG (HU13)."""

    __tablename__ = "uploaded_documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    filename = Column(String(500), nullable=False)
    file_type = Column(String(20))  # 'pdf' o 'md'
    file_size_bytes = Column(Integer)
    chunk_count = Column(Integer)
    processed = Column(Boolean, default=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relación con chunks
    chunks = relationship(
        "DocumentChunk",
        backref="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentChunk(Base):
    """Chunk de texto indexado en PGVector."""

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer,
        ForeignKey("uploaded_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_text = Column(Text)
    chunk_index = Column(Integer)
    embedding = Column(Vector(384))  # multilingual-e5-small produce 384d
    chunk_metadata = Column("metadata", JSONB)  # columna "metadata" es jsonb en DB
    created_at = Column(TIMESTAMP, server_default=func.now())
