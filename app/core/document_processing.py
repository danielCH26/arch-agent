"""
Procesamiento de documentos PDF y MD para RAG.

Issue: #8 - HU13 Subir archivos PDF/MD al RAG

Funciones puras (testeables sin DB ni Chainlit):
- validate_file_extension(filename) -> bool
- validate_file_size(size_bytes, max_bytes) -> bool
- load_document(file_path) -> list[Document]
- split_documents(documents, chunk_size, chunk_overlap) -> list[Document]
- process_file(file_path) -> list[Document] (orquesta load + split)
"""

import os
from pathlib import Path
from typing import List

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


# Constantes
ALLOWED_EXTENSIONS = {".pdf", ".md"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200


class DocumentProcessingError(Exception):
    """Error específico del procesamiento de documentos."""
    pass


def validate_file_extension(filename: str) -> bool:
    """
    Verifica que el archivo tenga extensión .pdf o .md.

    Returns:
        True si la extensión es válida
    """
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS


def validate_file_size(
    size_bytes: int,
    max_bytes: int = MAX_FILE_SIZE_BYTES,
) -> bool:
    """
    Verifica que el archivo no exceda el tamaño máximo.

    Args:
        size_bytes: tamaño del archivo en bytes
        max_bytes: límite máximo (default 10MB)

    Returns:
        True si el tamaño es válido (> 0 y <= max_bytes)
    """
    return 0 < size_bytes <= max_bytes


def load_document(file_path: str) -> List[Document]:
    """
    Carga un documento PDF o MD usando el loader apropiado.

    Args:
        file_path: ruta al archivo

    Returns:
        Lista de Documents (uno por página en PDFs, uno por archivo en MD)

    Raises:
        DocumentProcessingError: si el formato no es soportado,
                                  si el archivo no existe,
                                  o si no se puede extraer texto
    """
    path = Path(file_path)
    if not path.exists():
        raise DocumentProcessingError(f"Archivo no encontrado: {file_path}")

    ext = path.suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".md":
        # Usamos TextLoader en vez de UnstructuredMarkdownLoader porque
        # este último requiere spacy (en_core_web_sm) que no se puede
        # instalar automáticamente por permisos en algunos entornos.
        # Para el MVP, leer el MD como texto plano es suficiente.
        loader = TextLoader(file_path, encoding="utf-8")
    else:
        raise DocumentProcessingError(
            f"Formato no soportado: {ext}. "
            f"Solo se aceptan {sorted(ALLOWED_EXTENSIONS)}"
        )

    try:
        documents = loader.load()
    except Exception as e:
        raise DocumentProcessingError(
            f"No se pudo leer el archivo: {e}"
        )

    if not documents:
        raise DocumentProcessingError(
            "No se pudo extraer texto. ¿Es un PDF escaneado?"
        )

    return documents


def split_documents(
    documents: List[Document],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Document]:
    """
    Divide documentos en chunks usando RecursiveCharacterTextSplitter.

    Args:
        documents: lista de Documents a dividir
        chunk_size: tamaño de cada chunk en caracteres
        chunk_overlap: solapamiento entre chunks consecutivos

    Returns:
        Lista de chunks con metadata preservada
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(documents)


def process_file(file_path: str) -> List[Document]:
    """
    Orquesta load + split. Retorna chunks listos para embeddings.

    Args:
        file_path: ruta al archivo

    Returns:
        Lista de chunks con metadata preservada

    Raises:
        DocumentProcessingError: si hay error en cualquier paso
    """
    documents = load_document(file_path)
    return split_documents(documents)
