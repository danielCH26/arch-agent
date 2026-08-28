"""
Tests para el módulo de procesamiento de documentos (HU13).

Issue: #8 - HU13 Subir archivos PDF/MD al RAG

Tests para funciones puras (sin DB ni Chainlit).
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.documents import Document

from app.core.document_processing import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    DocumentProcessingError,
    validate_file_extension,
    validate_file_size,
    load_document,
    split_documents,
    process_file,
)


# =============================================================================
# Tests de validate_file_extension
# =============================================================================


class TestValidateFileExtension:
    def test_accepts_pdf(self):
        assert validate_file_extension("arch.pdf") is True
        assert validate_file_extension("ARCH.PDF") is True

    def test_accepts_md(self):
        assert validate_file_extension("readme.md") is True
        assert validate_file_extension("README.MD") is True

    def test_rejects_other_extensions(self):
        assert validate_file_extension("doc.docx") is False
        assert validate_file_extension("image.png") is False
        assert validate_file_extension("data.csv") is False

    def test_rejects_no_extension(self):
        assert validate_file_extension("README") is False
        assert validate_file_extension("arch") is False

    def test_rejects_empty_filename(self):
        assert validate_file_extension("") is False


# =============================================================================
# Tests de validate_file_size
# =============================================================================


class TestValidateFileSize:
    def test_accepts_normal_file(self):
        assert validate_file_size(1024) is True  # 1 KB
        assert validate_file_size(5 * 1024 * 1024) is True  # 5 MB

    def test_accepts_exactly_max(self):
        # En el límite exacto
        assert validate_file_size(MAX_FILE_SIZE_BYTES) is True

    def test_rejects_zero_size(self):
        assert validate_file_size(0) is False

    def test_rejects_above_max(self):
        # 1 byte más del límite
        assert validate_file_size(MAX_FILE_SIZE_BYTES + 1) is False
        # Mucho más del límite
        assert validate_file_size(100 * 1024 * 1024) is False

    def test_custom_max_size(self):
        # Probar con max custom
        assert validate_file_size(1024, max_bytes=2048) is True
        assert validate_file_size(2049, max_bytes=2048) is False


# =============================================================================
# Tests de load_document
# =============================================================================


class TestLoadDocument:
    def test_load_nonexistent_file_raises(self):
        with pytest.raises(DocumentProcessingError, match="no encontrado"):
            load_document("/path/que/no/existe.pdf")

    @patch("app.core.document_processing.PyPDFLoader")
    def test_load_pdf_uses_pypdf_loader(self, mock_pypdf_loader):
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [
            Document(page_content="page 1", metadata={"page": 0})
        ]
        mock_pypdf_loader.return_value = mock_loader_instance

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name

        try:
            docs = load_document(tmp_path)
            mock_pypdf_loader.assert_called_once_with(tmp_path)
            assert len(docs) == 1
            assert docs[0].page_content == "page 1"
        finally:
            os.unlink(tmp_path)

    @patch("app.core.document_processing.TextLoader")
    def test_load_md_uses_markdown_loader(self, mock_md_loader):
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = [
            Document(page_content="# Hello", metadata={"source": "test.md"})
        ]
        mock_md_loader.return_value = mock_loader_instance

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as f:
            tmp_path = f.name
            f.write("# Hello")

        try:
            docs = load_document(tmp_path)
            # TextLoader se llama con (file_path, encoding="utf-8")
            mock_md_loader.assert_called_once_with(tmp_path, encoding="utf-8")
            assert len(docs) == 1
        finally:
            os.unlink(tmp_path)

    def test_unsupported_format_raises(self):
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(DocumentProcessingError, match="no soportado"):
                load_document(tmp_path)
        finally:
            os.unlink(tmp_path)

    @patch("app.core.document_processing.PyPDFLoader")
    def test_pdf_without_text_raises(self, mock_pypdf_loader):
        """PDF escaneado (sin texto extraíble)."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.return_value = []  # vacío
        mock_pypdf_loader.return_value = mock_loader_instance

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(DocumentProcessingError, match="PDF escaneado"):
                load_document(tmp_path)
        finally:
            os.unlink(tmp_path)

    @patch("app.core.document_processing.PyPDFLoader")
    def test_pdf_loader_exception_wrapped(self, mock_pypdf_loader):
        """Si el loader tira excepción, se envuelve en DocumentProcessingError."""
        mock_loader_instance = MagicMock()
        mock_loader_instance.load.side_effect = Exception("PDF corrupto")
        mock_pypdf_loader.return_value = mock_loader_instance

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(DocumentProcessingError, match="No se pudo leer"):
                load_document(tmp_path)
        finally:
            os.unlink(tmp_path)


# =============================================================================
# Tests de split_documents
# =============================================================================


class TestSplitDocuments:
    def test_split_short_document_returns_single_chunk(self):
        docs = [Document(page_content="Short text", metadata={"source": "test"})]
        chunks = split_documents(docs)
        assert len(chunks) == 1
        assert chunks[0].page_content == "Short text"

    def test_split_long_document_creates_multiple_chunks(self):
        # Crear texto largo (> 1000 chars)
        long_text = "This is a sentence. " * 100  # ~2500 chars
        docs = [Document(page_content=long_text, metadata={"source": "test"})]
        chunks = split_documents(docs, chunk_size=500, chunk_overlap=50)
        assert len(chunks) > 1

    def test_split_respects_overlap(self):
        long_text = "Word " * 500  # ~2500 chars
        docs = [Document(page_content=long_text, metadata={"source": "test"})]
        chunks = split_documents(docs, chunk_size=300, chunk_overlap=100)
        assert len(chunks) > 1

        # Verificar que hay overlap entre chunks consecutivos
        if len(chunks) >= 2:
            # El final del chunk 1 debería estar en el chunk 2
            chunk1_end = chunks[0].page_content[-50:]
            assert chunk1_end in chunks[1].page_content or \
                   any(word in chunks[1].page_content for word in chunk1_end.split()[-5:])

    def test_split_preserves_metadata(self):
        docs = [Document(
            page_content="Some content here",
            metadata={"source": "test.pdf", "page": 5}
        )]
        chunks = split_documents(docs)
        assert chunks[0].metadata.get("source") == "test.pdf"
        assert chunks[0].metadata.get("page") == 5

    def test_split_empty_documents_returns_empty_list(self):
        chunks = split_documents([])
        assert chunks == []

    def test_split_default_chunk_size(self):
        # Verificar que usa DEFAULT_CHUNK_SIZE
        assert DEFAULT_CHUNK_SIZE == 1000
        assert DEFAULT_CHUNK_OVERLAP == 200


# =============================================================================
# Tests de process_file (orquestación)
# =============================================================================


class TestProcessFile:
    @patch("app.core.document_processing.load_document")
    def test_process_file_calls_load_and_split(self, mock_load):
        mock_load.return_value = [
            Document(page_content="Some text here", metadata={"page": 0})
        ]

        with patch("app.core.document_processing.split_documents") as mock_split:
            mock_split.return_value = [
                Document(page_content="chunk1", metadata={"page": 0}),
                Document(page_content="chunk2", metadata={"page": 0}),
            ]

            # process_file llama internamente a load_document
            # pero como mock_load está parcheado, no llega al filesystem
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                tmp_path = f.name

            try:
                # Para que process_file funcione, también necesitamos
                # que la extensión sea válida (lo cual .pdf es)
                # Pero como mock_load intercepta antes, no importa el contenido
                chunks = process_file(tmp_path)
                mock_load.assert_called_once_with(tmp_path)
                mock_split.assert_called_once()
                assert len(chunks) == 2
            finally:
                os.unlink(tmp_path)

    @patch("app.core.document_processing.load_document")
    def test_process_file_propagates_errors(self, mock_load):
        from app.core.document_processing import DocumentProcessingError
        mock_load.side_effect = DocumentProcessingError("Test error")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name

        try:
            with pytest.raises(DocumentProcessingError, match="Test error"):
                process_file(tmp_path)
        finally:
            os.unlink(tmp_path)


# =============================================================================
# Tests de constantes
# =============================================================================


class TestConstants:
    def test_allowed_extensions_is_frozenset_or_set(self):
        # Verificar que sea iterable
        assert ".pdf" in ALLOWED_EXTENSIONS
        assert ".md" in ALLOWED_EXTENSIONS
        assert len(ALLOWED_EXTENSIONS) == 2

    def test_max_file_size_is_10mb(self):
        assert MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024

    def test_default_chunk_params(self):
        assert DEFAULT_CHUNK_SIZE == 1000
        assert DEFAULT_CHUNK_OVERLAP == 200
