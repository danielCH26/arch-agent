import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.document_processing import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    DocumentProcessingError,
    process_file,
    validate_file_extension,
    validate_file_size,
)
from app.core.document_storage import (
    DocumentStorageError,
    check_duplicate,
    delete_document,
    get_document_by_id,
    get_user_documents,
    overwrite_document,
    save_document,
)
from app.core.embeddings import get_embeddings

router = APIRouter(prefix="/api/documents", tags=["documents"])


# --- Pydantic models ---------------------------------------------------------

class DocumentOut(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size_bytes: int
    chunk_count: int
    version: int
    created_at: str

    class Config:
        from_attributes = True


class DuplicateResponse(BaseModel):
    is_duplicate: bool
    existing_version: Optional[int] = None


# --- Helpers -----------------------------------------------------------------

def _require_document(user_id: int, doc_id: int) -> None:
    """Raise 403/404 if document doesn't exist or isn't owned by user."""
    doc = get_document_by_id(user_id, doc_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")
    return doc


# --- Routes -----------------------------------------------------------------

@router.get("/{project_id}", response_model=list[DocumentOut])
async def list_documents(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """List documents for a project."""
    docs = get_user_documents(
        user_id=current_user["user_id"],
        project_id=project_id,
    )
    return [
        DocumentOut(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            file_size_bytes=d.file_size_bytes,
            chunk_count=d.chunk_count,
            version=d.version,
            created_at=d.created_at.isoformat() if d.created_at else "",
        )
        for d in docs
    ]


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doc(
    doc_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Delete a document."""
    _require_document(current_user["user_id"], doc_id)
    deleted = delete_document(current_user["user_id"], doc_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado")


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    project_id: int,
    file: UploadFile,
    overwrite: bool = Query(
        False,
        description=(
            "Si ya existe un documento con el mismo nombre en este proyecto, "
            "sobrescribe la ultima version en lugar de crear una nueva."
        ),
    ),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a PDF or MD file and index it in PGVector.

    Handles duplicates:
    - Si el archivo ya existe para este user+project y `overwrite=false` (default):
      retorna 409 con `DuplicateResponse` (cliente debe confirmar y reintentar
      con `?overwrite=true`).
    - Si el archivo ya existe y `overwrite=true`: borra la version anterior
      (cascadea chunks) y crea una nueva con el mismo numero de version.
    - Si el archivo NO existe: crea version 1.
    """
    user_id = current_user["user_id"]
    filename = file.filename or "unnamed"

    # Validate extension
    if not validate_file_extension(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato no soportado. Solo: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read content and validate size
    content = await file.read()
    if not validate_file_size(len(content), MAX_FILE_SIZE_BYTES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El archivo excede el límite de {MAX_FILE_SIZE_BYTES // (1024*1024)} MB",
        )

    # Check for duplicate (despues de validar extension/size para no leak info)
    existing_version = check_duplicate(user_id, filename, project_id=project_id)
    if existing_version is not None and not overwrite:
        # El cliente debe confirmar explicitamente via ?overwrite=true.
        # Devolvemos 409 con un body que es un DuplicateResponse (no DocumentOut).
        # Para que FastAPI serialice bien, usamos JSONResponse manual.
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "is_duplicate": True,
                "existing_version": existing_version,
                "filename": filename,
                "detail": (
                    f"Ya existe '{filename}' (v{existing_version}) en este proyecto. "
                    "Reenvia con ?overwrite=true para sobrescribir."
                ),
            },
        )

    # Write to temp file for processing
    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Process file (load + split into chunks)
        try:
            chunks = process_file(tmp_path)
        except DocumentProcessingError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Compute embeddings for each chunk
        try:
            texts = [c.page_content for c in chunks]
            embeddings = get_embeddings().embed_documents(texts)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error al generar embeddings: {str(e)[:200]}",
            )

        # Store document and chunks
        try:
            if existing_version is not None and overwrite:
                # Borrar la version anterior (cascadea chunks) y crear nueva
                # con el mismo numero de version via overwrite_document.
                doc_id = overwrite_document(
                    user_id=user_id,
                    filename=filename,
                    file_type=suffix,
                    file_size_bytes=len(content),
                    chunks=chunks,
                    embeddings=embeddings,
                    project_id=project_id,
                )
            else:
                doc_id = save_document(
                    user_id=user_id,
                    filename=filename,
                    file_type=suffix,
                    file_size_bytes=len(content),
                    chunks=chunks,
                    embeddings=embeddings,
                    project_id=project_id,
                )
        except DocumentStorageError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        # Fetch the created document
        doc = get_document_by_id(user_id, doc_id)

        return DocumentOut(
            id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            version=doc.version,
            created_at=doc.created_at.isoformat() if doc.created_at else "",
        )

    finally:
        # Clean up temp file
        os.unlink(tmp_path)
