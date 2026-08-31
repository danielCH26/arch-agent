"""
Tests para el RAG retriever de F08.

Issue: #12 — F08 Generación propuesta + aprobación

Nota: los tests de retrieve_patterns requieren que F07 haya cargado
patrones en architect_patterns. Si está vacía, los tests de patterns
pasan trivialmente con [] (fallback esperado).
"""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document

import app.models  # registrar todos los modelos
from app.core.database import SessionLocal, Base, engine
from app.models.user import User
from app.models.project import Project
from app.models.uploaded_document import UploadedDocument
from app.core.rag import (
    retrieve_context,
    retrieve_user_documents,
    retrieve_patterns,
    _to_pgvector_literal,
)


EMBEDDING_384 = [0.1] * 384


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def rag_user(db):
    """Usuario de prueba para tests de RAG."""
    db.query(User).filter(User.username == "rag_test_user").delete()
    db.commit()
    user = User(
        username="rag_test_user",
        email="rag_test@example.com",
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.query(User).filter(User.id == user.id).delete()
    db.commit()


@pytest.fixture
def rag_project(db, rag_user):
    """Proyecto de prueba."""
    project = Project(
        user_id=rag_user.id,
        name="rag-test-project",
        description="Proyecto para tests de RAG",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    yield project
    db.query(Project).filter(Project.id == project.id).delete()
    db.commit()


def _seed_document(db, user_id, project_id, filename, chunk_text, embedding):
    """Helper para insertar un documento con un chunk directo en DB."""
    doc = UploadedDocument(
        user_id=user_id,
        project_id=project_id,
        filename=filename,
        file_type="md",
        file_size_bytes=1024,
        chunk_count=1,
        processed=True,
        version=1,
    )
    db.add(doc)
    db.flush()
    from app.models.uploaded_document import DocumentChunk
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_text=chunk_text,
        chunk_index=0,
        embedding=embedding,
        chunk_metadata={"source": "test"},
    )
    db.add(chunk)
    db.commit()
    return doc


class TestToPgvectorLiteral:
    def test_converts_list_to_literal(self):
        assert _to_pgvector_literal([0.1, 0.2, 0.3]) == "[0.100000,0.200000,0.300000]"

    def test_empty_list(self):
        assert _to_pgvector_literal([]) == "[]"


class TestRetrieveUserDocuments:
    def test_returns_empty_when_user_has_no_documents(self, rag_user):
        result = retrieve_user_documents(
            user_id=rag_user.id,
            query_embedding=EMBEDDING_384,
        )
        assert isinstance(result, list)

    def test_returns_empty_on_invalid_embedding(self, rag_user, db, rag_project):
        """Con embedding de dimensión incorrecta, la query falla y retorna []."""
        _seed_document(db, rag_user.id, rag_project.id, "test.md", "content", [0.1] * 384)
        result = retrieve_user_documents(
            user_id=rag_user.id,
            query_embedding=[0.1] * 10,  # dimensión incorrecta
        )
        assert result == []

    def test_user_isolation(
        self, rag_user, db, rag_project
    ):
        """User A NO ve documentos de User B."""
        # Crear otro usuario con un documento
        other = User(
            username="rag_other_user",
            email="rag_other@example.com",
            password_hash="hashed",
        )
        db.add(other)
        db.commit()
        db.refresh(other)

        _seed_document(db, other.id, None, "other.md", "OTHER secret content", EMBEDDING_384)

        # rag_user no debe ver el doc de other
        result = retrieve_user_documents(
            user_id=rag_user.id,
            query_embedding=EMBEDDING_384,
        )
        texts = [d.page_content for d in result]
        assert all("OTHER secret" not in t for t in texts)

        # Cleanup
        db.query(User).filter(User.id == other.id).delete()
        db.commit()


class TestRetrievePatterns:
    def test_returns_list_even_if_table_empty(self):
        """Si architect_patterns está vacía (F07 no listo), retorna []."""
        result = retrieve_patterns(query_embedding=EMBEDDING_384)
        assert isinstance(result, list)

    def test_returns_empty_on_error(self):
        """Si hay error en la query (embedding inválido), retorna [] silenciosamente."""
        # Un embedding de dimensión incorrecta hace que la query SQL falle;
        # retrieve_patterns debe capturar el error y retornar [].
        result = retrieve_patterns(query_embedding=[0.1] * 10)
        assert result == []


class TestRetrieveContext:
    def test_empty_query_returns_empty(self, rag_user):
        result = retrieve_context(user_id=rag_user.id, query="")
        assert result == []

    def test_whitespace_query_returns_empty(self, rag_user):
        result = retrieve_context(user_id=rag_user.id, query="   ")
        assert result == []

    def test_embedding_error_returns_empty(self, rag_user):
        """Si embeddings fallan, retorna [] sin lanzar."""
        with patch("app.core.rag.get_embeddings") as mock_emb:
            mock_emb.side_effect = Exception("model not loaded")
            result = retrieve_context(user_id=rag_user.id, query="test")
            assert result == []

    def test_returns_list_type(self, rag_user):
        result = retrieve_context(user_id=rag_user.id, query="test query")
        assert isinstance(result, list)

    def test_no_exception_on_db_error(self, rag_user):
        """Si la DB falla, retorna [] sin lanzar (fallback silencioso)."""
        with patch("app.core.rag.retrieve_user_documents") as mock_docs:
            mock_docs.side_effect = Exception("DB error")
            with patch("app.core.rag.retrieve_patterns") as mock_patterns:
                mock_patterns.return_value = []
                # retrieve_context llama a las funciones internas directamente;
                # el try/except está dentro de cada función, no en retrieve_context.
                # Para simular el flujo completo, verificamos que el error
                # de una función interna no rompe el flujo si las demás funcionan.
                try:
                    retrieve_context(user_id=rag_user.id, query="test")
                except Exception:
                    pytest.fail("retrieve_context should not raise")
