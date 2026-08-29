"""
Tests para /api/documents/* — upload, list, delete.

Las funciones de validación son puras (sin langchain).
Se extraen via exec() para evitar el import de langchain en document_processing.
"""

import pytest
import os

os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["JWT_SECRET_KEY"] = "test-secret!"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-32-chars!!"

# --- Extraer funciones puras de document_processing sin importar langchain ---
import re

_src = open("app/core/document_processing.py").read()

_allowed_ext_match = re.search(r"(ALLOWED_EXTENSIONS = \{[^}]+\})", _src)
_max_size_match = re.search(r"(MAX_FILE_SIZE_BYTES = [\d* ]+)", _src)
_validate_ext_fn = re.search(
    r"(def validate_file_extension.*?(?=\n\ndef |\\Z))", _src, re.DOTALL
)
_validate_size_fn = re.search(
    r"(def validate_file_size.*?(?=\n\ndef |\\Z))", _src, re.DOTALL
)

_pure_ns = {"__builtins__": __builtins__}
from pathlib import Path
_pure_ns["Path"] = Path
exec(
    _allowed_ext_match.group(1)
    + "\n"
    + _max_size_match.group(1)
    + "\n"
    + _validate_ext_fn.group(1)
    + "\n"
    + _validate_size_fn.group(1),
    _pure_ns,
)

validate_file_extension = _pure_ns["validate_file_extension"]
validate_file_size = _pure_ns["validate_file_size"]
ALLOWED_EXTENSIONS = _pure_ns["ALLOWED_EXTENSIONS"]
MAX_FILE_SIZE_BYTES = _pure_ns["MAX_FILE_SIZE_BYTES"]


class TestValidateFileExtension:
    """Tests de validación de extensiones."""

    def test_accepts_pdf(self):
        assert validate_file_extension("document.pdf") is True

    def test_accepts_md(self):
        assert validate_file_extension("readme.md") is True

    def test_accepts_uppercase_extension(self):
        assert validate_file_extension("DOCUMENT.PDF") is True
        assert validate_file_extension("README.MD") is True

    def test_rejects_docx(self):
        assert validate_file_extension("document.docx") is False

    def test_rejects_txt(self):
        assert validate_file_extension("notes.txt") is False

    def test_rejects_no_extension(self):
        assert validate_file_extension("document") is False

    def test_rejects_empty_filename(self):
        assert validate_file_extension("") is False

    def test_rejects_just_dot(self):
        assert validate_file_extension(".") is False

    def test_rejects_double_extension(self):
        assert validate_file_extension("file.pdf.txt") is False


class TestValidateFileSize:
    """Tests de validación de tamaño de archivo."""

    def test_accepts_small_file(self):
        assert validate_file_size(1024) is True  # 1 KB

    def test_accepts_file_at_limit(self):
        assert validate_file_size(MAX_FILE_SIZE_BYTES) is True

    def test_accepts_just_under_limit(self):
        assert validate_file_size(MAX_FILE_SIZE_BYTES - 1) is True

    def test_rejects_file_over_limit(self):
        assert validate_file_size(MAX_FILE_SIZE_BYTES + 1) is False

    def test_rejects_empty_file(self):
        assert validate_file_size(0) is False

    def test_rejects_negative_size(self):
        assert validate_file_size(-1) is False


class TestConstants:
    """Tests de constantes."""

    def test_allowed_extensions_only_pdf_and_md(self):
        assert ALLOWED_EXTENSIONS == {".pdf", ".md"}

    def test_max_file_size_is_10mb(self):
        assert MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024


class TestDocumentModels:
    """Tests de Pydantic models de documents (lazy import)."""

    def test_document_out_model(self):
        from app.api.documents import DocumentOut

        doc = DocumentOut(
            id=1,
            filename="test.pdf",
            file_type=".pdf",
            file_size_bytes=1024,
            chunk_count=5,
            version=1,
            created_at="2026-08-28T00:00:00",
        )
        assert doc.filename == "test.pdf"
        assert doc.version == 1
        assert doc.chunk_count == 5

    def test_duplicate_response_model(self):
        from app.api.documents import DuplicateResponse

        resp = DuplicateResponse(is_duplicate=True, existing_version=3)
        assert resp.is_duplicate is True
        assert resp.existing_version == 3


class TestDocumentProcessingErrors:
    """Tests de errores de procesamiento (lazy import)."""

    def test_document_processing_error(self):
        from app.core.document_processing import DocumentProcessingError

        err = DocumentProcessingError("File not found")
        assert str(err) == "File not found"

    def test_document_storage_error(self):
        from app.core.document_storage import DocumentStorageError

        err = DocumentStorageError("Constraint violation")
        assert "Constraint" in str(err)
