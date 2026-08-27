"""
Tests para el storage de documentos (HU13).

Issue: #8 - HU13 Subir archivos PDF/MD al RAG

Tests de integración con DB (usa PostgreSQL real).
"""

import os
import pytest
from unittest.mock import MagicMock
from langchain_core.documents import Document

from app.core.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.uploaded_document import UploadedDocument, DocumentChunk
from app.core.document_storage import (
    check_duplicate,
    save_document,
    get_user_documents,
    get_document_by_id,
    delete_document,
    overwrite_document,
    get_document_chunks,
    DocumentStorageError,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Crea las tablas en la DB de test."""
    Base.metadata.create_all(engine)
    yield
    # No dropeamos para no afectar otras suites


@pytest.fixture
def db():
    """Sesión de DB para tests."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_chunks():
    """Chunks de ejemplo para tests."""
    return [
        Document(page_content="Chunk 1 content", metadata={"page": 0}),
        Document(page_content="Chunk 2 content", metadata={"page": 0}),
        Document(page_content="Chunk 3 content", metadata={"page": 1}),
    ]


@pytest.fixture
def sample_embeddings():
    """Embeddings dummy (384d según multilingual-e5-small)."""
    return [[0.1] * 384 for _ in range(3)]


@pytest.fixture
def test_user(db):
    """Crea un usuario de prueba."""
    # Limpiar usuarios previos con este email
    db.query(User).filter(User.username == "test_user_hu13").delete()
    db.commit()

    user = User(
        username="test_user_hu13",
        email="test_hu13@example.com",
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    yield user

    # Cleanup
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


@pytest.fixture
def other_test_user(db):
    """Segundo usuario para tests de privacidad."""
    db.query(User).filter(User.username == "other_test_user_hu13").delete()
    db.commit()

    user = User(
        username="other_test_user_hu13",
        email="other_hu13@example.com",
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    yield user

    db.query(User).filter(User.id == user.id).delete()
    db.commit()


# =============================================================================
# Tests de check_duplicate
# =============================================================================


class TestCheckDuplicate:
    def test_returns_none_for_new_filename(self, test_user):
        result = check_duplicate(test_user.id, "new_doc.pdf")
        assert result is None

    def test_returns_version_for_existing_filename(self, test_user, sample_chunks, sample_embeddings):
        save_document(test_user.id, "existing.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        result = check_duplicate(test_user.id, "existing.pdf")
        assert result == 1

    def test_returns_max_version_after_multiple_uploads(
        self, test_user, sample_chunks, sample_embeddings
    ):
        save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        result = check_duplicate(test_user.id, "doc.pdf")
        assert result == 3

    def test_user_isolation_in_check(
        self, test_user, other_test_user, sample_chunks, sample_embeddings
    ):
        # User A sube un doc
        save_document(test_user.id, "shared_name.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        # User B no debe verlo
        result = check_duplicate(other_test_user.id, "shared_name.pdf")
        assert result is None


# =============================================================================
# Tests de save_document
# =============================================================================


class TestSaveDocument:
    def test_save_creates_document_and_chunks(
        self, test_user, sample_chunks, sample_embeddings, db
    ):
        doc_id = save_document(
            test_user.id, "test.pdf", "pdf", 5000,
            sample_chunks, sample_embeddings,
        )
        assert doc_id > 0

        # Verificar que se creó el documento
        doc = db.query(UploadedDocument).filter(UploadedDocument.id == doc_id).first()
        assert doc is not None
        assert doc.filename == "test.pdf"
        assert doc.file_type == "pdf"
        assert doc.file_size_bytes == 5000
        assert doc.chunk_count == 3
        assert doc.version == 1
        assert doc.processed is True
        assert doc.user_id == test_user.id

        # Verificar chunks
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        assert len(chunks) == 3
        assert chunks[0].chunk_index == 0
        assert chunks[0].chunk_text == "Chunk 1 content"
        assert chunks[2].chunk_index == 2

    def test_save_increments_version(
        self, test_user, sample_chunks, sample_embeddings
    ):
        id1 = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        id2 = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        id3 = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        assert id1 != id2 != id3

        # Verificar versiones
        db = SessionLocal()
        versions = db.query(UploadedDocument.version).filter(
            UploadedDocument.user_id == test_user.id,
            UploadedDocument.filename == "doc.pdf",
        ).order_by(UploadedDocument.version).all()
        db.close()
        assert [v[0] for v in versions] == [1, 2, 3]

    def test_save_with_mismatch_raises(
        self, test_user, sample_chunks, sample_embeddings
    ):
        # 3 chunks pero 2 embeddings
        with pytest.raises(DocumentStorageError, match="Mismatch"):
            save_document(
                test_user.id, "doc.pdf", "pdf", 1024,
                sample_chunks, sample_embeddings[:2],
            )


# =============================================================================
# Tests de get_user_documents (privacidad)
# =============================================================================


class TestGetUserDocuments:
    def test_returns_only_user_documents(
        self, test_user, other_test_user, sample_chunks, sample_embeddings
    ):
        # User A tiene 2 docs
        save_document(test_user.id, "a1.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        save_document(test_user.id, "a2.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        # User B tiene 1 doc
        save_document(other_test_user.id, "b1.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        # User A solo ve los suyos
        docs_a = get_user_documents(test_user.id)
        assert len(docs_a) == 2
        filenames_a = {d.filename for d in docs_a}
        assert filenames_a == {"a1.pdf", "a2.pdf"}

        # User B solo ve los suyos
        docs_b = get_user_documents(other_test_user.id)
        assert len(docs_b) == 1
        assert docs_b[0].filename == "b1.pdf"

    def test_returns_empty_for_new_user(self, test_user):
        docs = get_user_documents(test_user.id)
        assert docs == []

    def test_sorted_newest_first(
        self, test_user, sample_chunks, sample_embeddings
    ):
        save_document(test_user.id, "old.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        save_document(test_user.id, "new.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        docs = get_user_documents(test_user.id)
        # El más reciente primero
        assert docs[0].filename == "new.pdf"
        assert docs[1].filename == "old.pdf"

    def test_pagination_with_limit(
        self, test_user, sample_chunks, sample_embeddings
    ):
        for i in range(5):
            save_document(test_user.id, f"doc{i}.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        page1 = get_user_documents(test_user.id, limit=2, offset=0)
        page2 = get_user_documents(test_user.id, limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        # No se repiten
        ids1 = {d.id for d in page1}
        ids2 = {d.id for d in page2}
        assert ids1.isdisjoint(ids2)


# =============================================================================
# Tests de delete_document
# =============================================================================


class TestDeleteDocument:
    def test_delete_existing_document(
        self, test_user, sample_chunks, sample_embeddings
    ):
        doc_id = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        result = delete_document(test_user.id, doc_id)
        assert result is True

        # Verificar que ya no existe
        doc = get_document_by_id(test_user.id, doc_id)
        assert doc is None

    def test_delete_cascades_chunks(
        self, test_user, sample_chunks, sample_embeddings, db
    ):
        doc_id = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        chunks_before = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc_id
        ).count()
        assert chunks_before == 3

        delete_document(test_user.id, doc_id)

        chunks_after = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc_id
        ).count()
        assert chunks_after == 0

    def test_delete_nonexistent_returns_false(self, test_user):
        result = delete_document(test_user.id, 99999)
        assert result is False

    def test_delete_other_users_document_returns_false(
        self, test_user, other_test_user, sample_chunks, sample_embeddings
    ):
        # User A sube un doc
        doc_id = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        # User B intenta borrarlo
        result = delete_document(other_test_user.id, doc_id)
        assert result is False

        # Verificar que sigue existiendo
        doc = get_document_by_id(test_user.id, doc_id)
        assert doc is not None


# =============================================================================
# Tests de overwrite_document
# =============================================================================


class TestOverwriteDocument:
    def test_overwrite_existing(
        self, test_user, sample_chunks, sample_embeddings, db
    ):
        # Crear v1
        id_v1 = save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)

        # Sobrescribir
        new_chunks = [Document(page_content="NEW content", metadata={})]
        new_embeddings = [[0.5] * 384]
        id_new = overwrite_document(
            test_user.id, "doc.pdf", "pdf", 2048,
            new_chunks, new_embeddings,
        )

        # IDs son diferentes (es un nuevo doc)
        assert id_new != id_v1

        # Pero la versión sigue siendo 1
        new_doc = db.query(UploadedDocument).filter(
            UploadedDocument.id == id_new
        ).first()
        assert new_doc.version == 1
        assert new_doc.file_size_bytes == 2048

        # El viejo no existe
        old_doc = db.query(UploadedDocument).filter(
            UploadedDocument.id == id_v1
        ).first()
        assert old_doc is None

        # El check_duplicate devuelve 1 (no 2)
        assert check_duplicate(test_user.id, "doc.pdf") == 1

    def test_overwrite_when_no_existing_creates_v1(
        self, test_user, sample_chunks, sample_embeddings
    ):
        # No existe → debe crear v1
        chunks = [Document(page_content="First content", metadata={})]
        embeddings = [[0.1] * 384]
        doc_id = overwrite_document(
            test_user.id, "new.pdf", "pdf", 1024,
            chunks, embeddings,
        )
        assert doc_id > 0

        assert check_duplicate(test_user.id, "new.pdf") == 1

    def test_overwrite_when_v2_exists_keeps_v2(
        self, test_user, sample_chunks, sample_embeddings, db
    ):
        # Crear v1 y v2
        save_document(test_user.id, "doc.pdf", "pdf", 1024, sample_chunks, sample_embeddings)
        save_document(test_user.id, "doc.pdf", "pdf", 2048, sample_chunks, sample_embeddings)

        # Sobrescribir → debería reemplazar v2 (la más alta)
        new_chunks = [Document(page_content="REPLACED v2", metadata={})]
        new_embeddings = [[0.9] * 384]
        overwrite_document(test_user.id, "doc.pdf", "pdf", 9999, new_chunks, new_embeddings)

        # Versión sigue siendo 2
        docs = db.query(UploadedDocument).filter(
            UploadedDocument.filename == "doc.pdf",
            UploadedDocument.user_id == test_user.id,
        ).order_by(UploadedDocument.version).all()
        assert len(docs) == 2
        assert docs[0].version == 1
        assert docs[1].version == 2  # Sobrescrita, no 3


# =============================================================================
# Tests de get_document_chunks
# =============================================================================


class TestGetDocumentChunks:
    def test_returns_chunks_ordered_by_index(
        self, test_user, sample_chunks, sample_embeddings
    ):
        doc_id = save_document(
            test_user.id, "doc.pdf", "pdf", 1024,
            sample_chunks, sample_embeddings,
        )
        chunks = get_document_chunks(doc_id)
        assert len(chunks) == 3
        assert [c.chunk_index for c in chunks] == [0, 1, 2]

    def test_returns_empty_for_no_chunks(self):
        chunks = get_document_chunks(99999)
        assert chunks == []
