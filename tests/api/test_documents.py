"""
Tests para /api/documents/* — upload, list, delete.

Las funciones de validación son puras (sin langchain).
Se extraen via exec() para evitar el import de langchain en document_processing.
"""

import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["JWT_SECRET_KEY"] = "test-secret!"  # solo para el import
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


# =============================================================================
# Tests HTTP del endpoint /api/documents/upload (issue #8 - HU13)
#
# Cubre el bug G4 del audit: el endpoint debe leer ?overwrite=true y
# retornar 409 con DuplicateResponse cuando hay duplicado y overwrite=false.
# =============================================================================


class TestUploadEndpointDuplicates:
    """POST /api/documents/upload — manejo de duplicados y overwrite."""

    @staticmethod
    def _run_upload(**kwargs):
        """Helper para correr el endpoint async en tests sync."""
        from app.api.documents import upload_document
        import asyncio
        return asyncio.run(upload_document(**kwargs))

    def _fake_upload_file(self, content: bytes = b"fake-pdf-content", filename: str = "test.pdf"):
        """Crea un UploadFile-like mock con read() async."""
        f = MagicMock()
        f.filename = filename
        f.read = AsyncMock(return_value=content)
        return f

    def _fake_doc(self, *, doc_id: int = 42, version: int = 1):
        """Crea un Document ORM-like con campos JSON-serializables."""
        from datetime import datetime
        doc = MagicMock()
        doc.id = doc_id
        doc.filename = "test.pdf"
        doc.file_type = ".pdf"
        doc.file_size_bytes = 100
        doc.chunk_count = 1
        doc.version = version
        doc.created_at = datetime(2026, 1, 1, 12, 0, 0)
        return doc

    @patch("app.api.documents.check_duplicate")
    def test_duplicate_returns_409_with_version_info(self, mock_check):
        """Sin ?overwrite=true y archivo duplicado → 409 con version info."""
        mock_check.return_value = 2

        result = self._run_upload(
            project_id=1,
            file=self._fake_upload_file(),
            overwrite=False,
            current_user={"user_id": 1, "username": "testuser", "jti": None},
        )

        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 409
        import json
        body = json.loads(result.body)
        assert body["is_duplicate"] is True
        assert body["existing_version"] == 2
        assert "test.pdf" in body["detail"]
        assert "v2" in body["detail"]
        assert "overwrite=true" in body["detail"]

    @patch("app.api.documents.check_duplicate")
    @patch("app.api.documents.overwrite_document")
    @patch("app.api.documents.get_document_by_id")
    @patch("app.api.documents.get_embeddings")
    @patch("app.api.documents.process_file")
    def test_overwrite_true_calls_overwrite_document(
        self, mock_process, mock_get_emb, mock_get_doc, mock_overwrite, mock_check,
    ):
        """Con ?overwrite=true y duplicado → llama overwrite_document (preserva version)."""
        mock_check.return_value = 2  # hay duplicado v2
        mock_process.return_value = [MagicMock(page_content="chunk")]
        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1] * 384]
        mock_get_emb.return_value = mock_emb
        mock_overwrite.return_value = 42  # doc_id del nuevo doc
        mock_get_doc.return_value = self._fake_doc(doc_id=42, version=2)  # MISMA version

        result = self._run_upload(
            project_id=1,
            file=self._fake_upload_file(),
            overwrite=True,
            current_user={"user_id": 1, "username": "testuser", "jti": None},
        )

        # overwrite_document debe ser llamado (no save_document)
        mock_overwrite.assert_called_once()
        # Devuelve DocumentOut con la MISMA version que tenia antes
        assert result.version == 2
        assert result.id == 42

    @patch("app.api.documents.check_duplicate")
    @patch("app.api.documents.save_document")
    @patch("app.api.documents.get_document_by_id")
    @patch("app.api.documents.get_embeddings")
    @patch("app.api.documents.process_file")
    def test_no_duplicate_calls_save_with_version_1(
        self, mock_process, mock_get_emb, mock_get_doc, mock_save, mock_check,
    ):
        """Sin duplicado → save_document con version=1."""
        mock_check.return_value = None
        mock_process.return_value = [MagicMock(page_content="chunk")]
        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = [[0.1] * 384]
        mock_get_emb.return_value = mock_emb
        mock_save.return_value = 10
        mock_get_doc.return_value = self._fake_doc(doc_id=10, version=1)

        result = self._run_upload(
            project_id=1,
            file=self._fake_upload_file(filename="nuevo.pdf"),
            overwrite=False,
            current_user={"user_id": 1, "username": "testuser", "jti": None},
        )

        mock_save.assert_called_once()
        assert result.version == 1
        assert result.id == 10


class TestEmbeddingsAreReal:
    """Verifica que el stub _DummyEmbeddings ya no existe en app/core/embeddings.py.

    El audit (issue #8) detecto que embeddings eran stub [0.1]*384.
    El fix es usar HuggingFaceEmbeddings con multilingual-e5-small.

    Solo verificamos configuracion (no instanciamos la clase porque
    requiere sentence-transformers + torch instalados).
    """

    def test_embeddings_module_does_not_export_dummy(self):
        """app.core.embeddings NO debe exportar _DummyEmbeddings."""
        from app.core import embeddings
        assert not hasattr(embeddings, "_DummyEmbeddings"), (
            "_DummyEmbeddings stub fue eliminado. "
            "Usa HuggingFaceEmbeddings (multilingual-e5-small) en su lugar."
        )

    def test_embeddings_module_imports_huggingface(self):
        """Verifica que el modulo importa HuggingFaceEmbeddings de langchain."""
        # Si esto cambia (e.g. alguien migra a langchain-huggingface),
        # hay que actualizar el test y probablemente EMBEDDING_MODEL_NAME.
        import inspect

        from app.core import embeddings

        source = inspect.getsource(embeddings)
        assert "HuggingFaceEmbeddings" in source, (
            "app/core/embeddings.py debe usar HuggingFaceEmbeddings"
        )

    def test_embeddings_model_name_is_multilingual_e5_small(self):
        """El modelo debe ser multilingual-e5-small (issue #8 spec)."""
        from app.core.embeddings import EMBEDDING_MODEL_NAME

        assert EMBEDDING_MODEL_NAME == "intfloat/multilingual-e5-small"

    def test_embeddings_dim_is_384(self):
        """La dimension debe matchear schema.sql (vector(384))."""
        from app.core.embeddings import EMBEDDING_DIM

        assert EMBEDDING_DIM == 384

    def test_get_embeddings_returns_huggingface_instance(self):
        """get_embeddings() debe devolver HuggingFaceEmbeddings.

        Requiere sentence-transformers instalado. Si no esta, el test
        se saltea con un mensaje claro (no falla).
        """
        pytest.importorskip("sentence_transformers", reason="sentence-transformers no instalado")

        from app.core.embeddings import get_embeddings
        from langchain_community.embeddings import HuggingFaceEmbeddings

        emb = get_embeddings()
        assert isinstance(emb, HuggingFaceEmbeddings), (
            f"Esperaba HuggingFaceEmbeddings, obtuve {type(emb).__name__}"
        )
        # El singleton es cacheado: la segunda llamada devuelve la misma instancia
        assert get_embeddings() is emb
