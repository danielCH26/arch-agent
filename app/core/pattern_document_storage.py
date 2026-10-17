"""
Storage de fuentes subidas al catalogo curado de patrones.

Este modulo guarda chunks internos en architect_pattern_chunks para enriquecer
la busqueda semantica, sin modificar los campos curados de architect_patterns.
"""

from pathlib import Path
from typing import List

from langchain_core.documents import Document
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.architect_pattern import ArchitectPattern
from app.models.architect_pattern_chunk import ArchitectPatternChunk


class PatternStorageError(Exception):
    """Error especifico del storage de fuentes de patrones."""

    pass


def _source_type_from_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    if ext == "md":
        return "md"
    return ext or "unknown"


def save_pattern_chunks(
    pattern_id: int,
    chunks: List[Document],
    embeddings: List[List[float]],
    filename: str,
    chunk_type: str = "source_upload",
) -> int:
    """
    Inserta chunks en architect_pattern_chunks asociados a un patron existente.

    Guarda filename/source_type en chunk_metadata y retorna la cantidad de
    chunks insertados. No modifica architect_patterns.

    Short-circuit: el ``pattern_id`` se valida SIEMPRE, incluso cuando
    ``chunks`` viene vacio. Recien despues, si no hay chunks, se devuelve 0
    sin insertar nada. Asi ``scripts/ingest_pattern_source.py`` no imprime
    "Ingesta completada: 0 chunks" para un patron inexistente
    (PR #102 round 3, Laura).
    """
    if len(chunks) != len(embeddings):
        raise PatternStorageError(
            f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings"
        )

    db = SessionLocal()
    try:
        pattern_exists = db.query(ArchitectPattern.id).filter(
            ArchitectPattern.id == pattern_id,
        ).first()
        if pattern_exists is None:
            raise PatternStorageError(f"pattern_id {pattern_id} no existe")

        # Empty input: ya se valido el pattern_id, asi que no hay nada que asociar.
        if not chunks:
            return 0

        metadata = {
            "filename": filename,
            "source_type": _source_type_from_filename(filename),
        }

        for chunk, embedding in zip(chunks, embeddings):
            chunk_record = ArchitectPatternChunk(
                pattern_id=pattern_id,
                chunk_type=chunk_type,
                chunk_text=chunk.page_content,
                embedding=embedding,
                chunk_metadata=metadata,
            )
            db.add(chunk_record)

        db.commit()
        return len(chunks)
    except PatternStorageError:
        db.rollback()
        raise
    except IntegrityError as e:
        db.rollback()
        raise PatternStorageError(f"Constraint violation: {e}")
    except Exception as e:
        db.rollback()
        raise PatternStorageError(f"Error al guardar chunks de patron: {e}")
    finally:
        db.close()


def get_pattern_source_chunks(pattern_id: int) -> List[ArchitectPatternChunk]:
    """Lista los chunks source_upload de un patron para curacion asistida."""
    db = SessionLocal()
    try:
        return db.query(ArchitectPatternChunk).filter(
            ArchitectPatternChunk.pattern_id == pattern_id,
            ArchitectPatternChunk.chunk_type == "source_upload",
        ).order_by(ArchitectPatternChunk.id).all()
    finally:
        db.close()
