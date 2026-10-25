"""
Storage de documentos subidos al RAG (HU13).

Issue: #8 - HU13 Subir archivos PDF/MD al RAG

Funciones CRUD sobre uploaded_documents y document_chunks:
- check_duplicate: detecta si ya existe un filename para el user
- save_document: crea nuevo documento con versión + chunks
- get_user_documents: lista documentos del user (paginated)
- delete_document: borra documento (verificando ownership)
- overwrite_document: borra versión anterior y crea nueva

Todas las funciones filtran por user_id (privacidad).
"""

from typing import List, Optional

from sqlalchemy import select, desc, func
from sqlalchemy.exc import IntegrityError
from langchain_core.documents import Document

from app.core.database import SessionLocal
from app.models.uploaded_document import UploadedDocument, DocumentChunk


class DocumentStorageError(Exception):
    """Error específico del storage de documentos."""
    pass


def check_duplicate(user_id: int, filename: str, project_id: Optional[int] = None) -> Optional[int]:
    """
    Verifica si el user ya tiene un documento con ese filename.

    El parámetro project_id se ignora a efectos de la búsqueda de duplicados,
    ya que la constraint UNIQUE es (user_id, filename, version) sin project_id.
    Esto significa que un archivo con el mismo nombre no puede tener la misma
    versión en ningún proyecto — un documento es único globalmente por usuario
    y nombre, no por proyecto.

    Args:
        user_id: ID del usuario
        filename: nombre del archivo
        project_id: ID del proyecto (aceptado por compatibilidad, ignorado)

    Returns:
        Versión más alta existente (1, 2, 3...) o None si no existe
    """
    db = SessionLocal()
    try:
        result = db.query(func.max(UploadedDocument.version)).filter(
            UploadedDocument.user_id == user_id,
            UploadedDocument.filename == filename,
        ).scalar()
        return result
    finally:
        db.close()


def save_document(
    user_id: int,
    filename: str,
    file_type: str,
    file_size_bytes: int,
    chunks: List[Document],
    embeddings: List[List[float]],
    project_id: Optional[int] = None,
) -> int:
    """
    Crea un nuevo documento con sus chunks.

    Calcula automáticamente la versión (max + 1).

    Args:
        user_id: ID del usuario
        project_id: ID del proyecto (opcional, para asociar el doc al proyecto)

    Returns:
        document_id del documento creado

    Raises:
        DocumentStorageError: si hay error al guardar
    """
    if len(chunks) != len(embeddings):
        raise DocumentStorageError(
            f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings"
        )

    db = SessionLocal()
    try:
        # Calcular versión (por proyecto, si se pasa project_id)
        max_version = check_duplicate(user_id, filename, project_id=project_id)
        new_version = (max_version or 0) + 1

        # Crear documento
        doc = UploadedDocument(
            user_id=user_id,
            project_id=project_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            chunk_count=len(chunks),
            processed=True,
            version=new_version,
        )
        db.add(doc)
        db.flush()  # Para obtener doc.id

        # Crear chunks
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_record = DocumentChunk(
                document_id=doc.id,
                chunk_text=chunk.page_content,
                chunk_index=idx,
                embedding=embedding,  # PGVector maneja la conversión
                chunk_metadata=chunk.metadata if chunk.metadata else None,
            )
            db.add(chunk_record)

        db.commit()
        return doc.id
    except IntegrityError as e:
        db.rollback()
        raise DocumentStorageError(f"Constraint violation: {e}")
    except Exception as e:
        db.rollback()
        raise DocumentStorageError(f"Error al guardar documento: {e}")
    finally:
        db.close()


def get_user_documents(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    project_id: Optional[int] = None,
) -> List[UploadedDocument]:
    """
    Lista los documentos del usuario, ordenados por más recientes.

    Args:
        user_id: ID del usuario (filtro de privacidad)
        project_id: ID del proyecto (opcional, filtra por proyecto activo)
        limit: máximo de documentos a retornar
        offset: offset para paginación

    Returns:
        Lista de UploadedDocument
    """
    db = SessionLocal()
    try:
        query = db.query(UploadedDocument).filter(
            UploadedDocument.user_id == user_id,
        ).order_by(desc(UploadedDocument.created_at))

        if project_id is not None:
            query = query.filter(UploadedDocument.project_id == project_id)

        docs = query.limit(limit).offset(offset).all()
        return docs
    finally:
        db.close()


def get_document_by_id(user_id: int, document_id: int) -> Optional[UploadedDocument]:
    """
    Obtiene un documento por ID, verificando ownership.

    Returns:
        UploadedDocument si existe y pertenece al user, None si no
    """
    db = SessionLocal()
    try:
        doc = db.query(UploadedDocument).filter(
            UploadedDocument.id == document_id,
            UploadedDocument.user_id == user_id,  # ← privacidad
        ).first()
        return doc
    finally:
        db.close()


def delete_document(user_id: int, document_id: int) -> bool:
    """
    Borra un documento y todos sus chunks (CASCADE).

    Returns:
        True si se borró, False si no existía o no era del user
    """
    db = SessionLocal()
    try:
        doc = db.query(UploadedDocument).filter(
            UploadedDocument.id == document_id,
            UploadedDocument.user_id == user_id,  # ← verificación
        ).first()
        if doc is None:
            return False
        db.delete(doc)  # chunks se borran por CASCADE
        db.commit()
        return True
    finally:
        db.close()


def overwrite_document(
    user_id: int,
    filename: str,
    file_type: str,
    file_size_bytes: int,
    chunks: List[Document],
    embeddings: List[List[float]],
    project_id: Optional[int] = None,
) -> int:
    """
    Borra la versión actual del documento y crea una nueva con el mismo número.

    Útil cuando el usuario eligió "Sobrescribir" en el popup de duplicados.

    Si se pasa `project_id`, filtra la versión a sobrescribir por (user_id,
    filename, project_id). Esto es importante porque un mismo usuario podría
    tener el mismo filename en proyectos distintos (v1 en proyecto A, v1 en B).

    Returns:
        document_id del nuevo documento
    """
    db = SessionLocal()
    try:
        # Buscar versión actual
        query = db.query(UploadedDocument).filter(
            UploadedDocument.user_id == user_id,
            UploadedDocument.filename == filename,
        )
        if project_id is not None:
            query = query.filter(UploadedDocument.project_id == project_id)
        current = query.order_by(desc(UploadedDocument.version)).first()

        if current is None:
            # No existe → equivalente a save_document con version=1
            return save_document(
                user_id=user_id,
                filename=filename,
                file_type=file_type,
                file_size_bytes=file_size_bytes,
                chunks=chunks,
                embeddings=embeddings,
                project_id=project_id,
            )

        # Borrar la versión actual (chunks por CASCADE)
        version_to_keep = current.version
        db.delete(current)
        db.flush()

        # Crear nueva con mismo número de versión
        new_doc = UploadedDocument(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            chunk_count=len(chunks),
            processed=True,
            version=version_to_keep,
            project_id=project_id,
        )
        db.add(new_doc)
        db.flush()

        # Crear chunks
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_record = DocumentChunk(
                document_id=new_doc.id,
                chunk_text=chunk.page_content,
                chunk_index=idx,
                embedding=embedding,
                chunk_metadata=chunk.metadata if chunk.metadata else None,
            )
            db.add(chunk_record)

        db.commit()
        return new_doc.id
    except Exception as e:
        db.rollback()
        raise DocumentStorageError(f"Error al sobrescribir: {e}")
    finally:
        db.close()


def save_document_pending(
    user_id: int,
    filename: str,
    file_type: str,
    file_size_bytes: int,
    chunk_count: int,
    project_id: Optional[int] = None,
) -> int:
    """
    Crea un documento con processed=False (sin chunks aún).
    Los chunks + embeddings se guardan después en background.

    Returns:
        document_id del documento creado
    """
    db = SessionLocal()
    try:
        max_version = check_duplicate(user_id, filename, project_id=project_id)
        new_version = (max_version or 0) + 1

        doc = UploadedDocument(
            user_id=user_id,
            project_id=project_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            chunk_count=chunk_count,
            processed=False,
            version=new_version,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id
    except IntegrityError as e:
        db.rollback()
        raise DocumentStorageError(f"Constraint violation: {e}")
    except Exception as e:
        db.rollback()
        raise DocumentStorageError(f"Error al guardar documento: {e}")
    finally:
        db.close()


def overwrite_document_pending(
    user_id: int,
    filename: str,
    file_type: str,
    file_size_bytes: int,
    chunk_count: int,
    project_id: Optional[int] = None,
) -> int:
    """
    Borra la versión actual del documento y crea una nueva pending (processed=False).
    Los chunks + embeddings se guardan después en background.

    Returns:
        document_id del nuevo documento
    """
    db = SessionLocal()
    try:
        query = db.query(UploadedDocument).filter(
            UploadedDocument.user_id == user_id,
            UploadedDocument.filename == filename,
        )
        if project_id is not None:
            query = query.filter(UploadedDocument.project_id == project_id)
        current = query.order_by(desc(UploadedDocument.version)).first()

        if current is None:
            return save_document_pending(
                user_id=user_id,
                filename=filename,
                file_type=file_type,
                file_size_bytes=file_size_bytes,
                chunk_count=chunk_count,
                project_id=project_id,
            )

        version_to_keep = current.version
        db.delete(current)
        db.flush()

        new_doc = UploadedDocument(
            user_id=user_id,
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            chunk_count=chunk_count,
            processed=False,
            version=version_to_keep,
            project_id=project_id,
        )
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        return new_doc.id
    except Exception as e:
        db.rollback()
        raise DocumentStorageError(f"Error al sobrescribir: {e}")
    finally:
        db.close()


def save_chunks_and_mark_processed(
    doc_id: int,
    chunks: List[Document],
    embeddings: List[List[float]],
) -> None:
    """
    Guarda los chunks con sus embeddings y marca el documento como processed=True.
    Se llama en background después del upload.

    Raises:
        DocumentStorageError: si hay error al guardar
    """
    if len(chunks) != len(embeddings):
        raise DocumentStorageError(
            f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings"
        )

    db = SessionLocal()
    try:
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_record = DocumentChunk(
                document_id=doc_id,
                chunk_text=chunk.page_content,
                chunk_index=idx,
                embedding=embedding,
                chunk_metadata=chunk.metadata if chunk.metadata else None,
            )
            db.add(chunk_record)

        db.query(UploadedDocument).filter(
            UploadedDocument.id == doc_id
        ).update({"processed": True})

        db.commit()
    except Exception as e:
        db.rollback()
        raise DocumentStorageError(f"Error al guardar chunks: {e}")
    finally:
        db.close()


def get_document_chunks(document_id: int) -> List[DocumentChunk]:
    """
    Obtiene todos los chunks de un documento (ordenados por chunk_index).
    """
    db = SessionLocal()
    try:
        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id,
        ).order_by(DocumentChunk.chunk_index).all()
        return chunks
    finally:
        db.close()
