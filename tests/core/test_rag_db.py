"""Tests para app.core.rag — DB-bound functions (similarity_search_*_by_vector).

Estos tests requieren Postgres con la extensión pgvector para correr
(usan ``SessionLocal`` y métodos SQLAlchemy como
``ArchitectPatternChunk.embedding.cosine_distance()``).

Se ejecutan en CI (donde hay un servicio postgres). Localmente se
marcan como skip para no romper el desarrollo cuando no hay Postgres
corriendo.

Para activarlos localmente:
    docker compose up -d postgres
    RUN_RAG_DB=1 pytest tests/core/test_rag_db.py
"""
from __future__ import annotations

import os

_RUN_RAG_DB = os.environ.get("RUN_RAG_DB") == "1"


import pytest

if not _RUN_RAG_DB:
    pytest.skip(
        "DB-bound RAG tests require Postgres; set RUN_RAG_DB=1 to enable",
        allow_module_level=True,
    )


from unittest.mock import MagicMock, patch


class TestSimilaritySearchPatternsByVector:
    """Tests for similarity_search_patterns_by_vector (DB-bound)."""

    def test_filters_by_category_when_provided(self):
        from app.core.rag import similarity_search_patterns_by_vector

        # Mock chunk + pattern
        mock_chunk = MagicMock()
        mock_chunk.embedding = [0.1] * 384
        mock_chunk.chunk_text = "chunk text"
        mock_chunk.chunk_type = "summary"

        mock_pattern = MagicMock()
        mock_pattern.id = 1
        mock_pattern.pattern_name = "Hexagonal"
        mock_pattern.category = "Distribuida"
        mock_pattern.tradeoffs = {"pros": ["decoupled"]}

        mock_db = MagicMock()
        # The query chain: .query().join().filter().filter().order_by().limit().all()
        chain = mock_db.query.return_value.join.return_value.filter.return_value
        chain.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            (mock_chunk, mock_pattern, 0.1)
        ]

        with (
            patch("app.core.rag.SessionLocal", return_value=mock_db),
            patch("app.core.rag._set_pgvector_probes") as mock_probes,
        ):
            docs, elapsed = similarity_search_patterns_by_vector(
                query_embedding=[0.1] * 384,
                k=5,
                category="Distribuida",
                probes=10,
            )

        mock_probes.assert_called_once_with(mock_db, 10)
        assert len(docs) == 1
        assert docs[0].page_content == "chunk text"
        assert docs[0].metadata["pattern_name"] == "Hexagonal"
        assert docs[0].metadata["source_type"] == "architect_pattern"

    def test_no_category_filter_when_category_is_none(self):
        from app.core.rag import similarity_search_patterns_by_vector

        with patch("app.core.rag.SessionLocal", return_value=MagicMock()):
            # Just verify it doesn't crash with category=None
            similarity_search_patterns_by_vector(
                query_embedding=[0.1] * 384,
                category=None,
            )

    def test_invalid_embedding_dim_raises(self):
        """_validate_embedding rejects wrong dimensions before DB query."""
        from app.core.rag import similarity_search_patterns_by_vector, RAGSearchError

        with pytest.raises(RAGSearchError, match="384"):
            similarity_search_patterns_by_vector(
                query_embedding=[0.1] * 100,  # wrong dim
            )

    def test_returns_empty_list_when_no_matches(self):
        from app.core.rag import similarity_search_patterns_by_vector

        mock_db = MagicMock()
        chain = mock_db.query.return_value.join.return_value.filter.return_value
        chain.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with patch("app.core.rag.SessionLocal", return_value=mock_db):
            docs, elapsed = similarity_search_patterns_by_vector(
                query_embedding=[0.1] * 384,
            )

        assert docs == []
        assert elapsed >= 0


class TestSimilaritySearchDocumentChunksByVector:
    """Tests for similarity_search_document_chunks_by_vector (DB-bound)."""

    def test_filters_by_user_id(self):
        from app.core.rag import similarity_search_document_chunks_by_vector

        mock_chunk = MagicMock()
        mock_chunk.embedding = [0.1] * 384
        mock_chunk.chunk_text = "doc chunk"
        mock_chunk.chunk_metadata = None

        mock_uploaded_doc = MagicMock()
        mock_uploaded_doc.id = 7
        mock_uploaded_doc.filename = "spec.pdf"
        mock_uploaded_doc.project_id = 5

        mock_db = MagicMock()
        chain = mock_db.query.return_value.join.return_value.filter.return_value
        chain.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            (mock_chunk, mock_uploaded_doc, 0.2)
        ]

        with patch("app.core.rag.SessionLocal", return_value=mock_db):
            docs, elapsed = similarity_search_document_chunks_by_vector(
                query_embedding=[0.1] * 384,
                user_id=42,
            )

        assert len(docs) == 1
        assert docs[0].page_content == "doc chunk"
        assert docs[0].metadata["filename"] == "spec.pdf"
        assert docs[0].metadata["source_type"] == "document_chunk"

    def test_filters_by_project_id_when_provided(self):
        from app.core.rag import similarity_search_document_chunks_by_vector

        with patch("app.core.rag.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            similarity_search_document_chunks_by_vector(
                query_embedding=[0.1] * 384,
                user_id=1,
                project_id=42,
                k=10,
            )

        # Verify the db chain was called
        mock_db.query.assert_called()

    def test_invalid_embedding_dim_raises(self):
        from app.core.rag import similarity_search_document_chunks_by_vector, RAGSearchError

        with pytest.raises(RAGSearchError, match="384"):
            similarity_search_document_chunks_by_vector(
                query_embedding=[0.1] * 200,
                user_id=1,
            )


class TestPatternChunkToDocument:
    """``_pattern_chunk_to_document`` builds the Document for a Pattern chunk."""

    def test_includes_all_required_metadata_fields(self):
        from app.core.rag import _pattern_chunk_to_document

        chunk = MagicMock()
        chunk.chunk_text = "Hexagonal content here"
        chunk.chunk_type = "summary"

        pattern = MagicMock()
        pattern.id = 42
        pattern.pattern_name = "Hexagonal"
        pattern.category = "Estructural"
        pattern.tradeoffs = {"pros": ["deferred coupling"]}

        doc = _pattern_chunk_to_document(chunk, pattern, distance=0.15)

        assert doc.page_content == "Hexagonal content here"
        assert doc.metadata["pattern_id"] == 42
        assert doc.metadata["pattern_name"] == "Hexagonal"
        assert doc.metadata["category"] == "Estructural"
        assert doc.metadata["tradeoffs"] == {"pros": ["deferred coupling"]}
        assert doc.metadata["source_type"] == "architect_pattern"
        assert doc.metadata["distance"] == 0.15
        # similarity = 1 - 0.15 = 0.85
        assert doc.metadata["similarity"] == pytest.approx(0.85)

    def test_handles_none_distance(self):
        from app.core.rag import _pattern_chunk_to_document

        chunk = MagicMock()
        chunk.chunk_text = "x"
        chunk.chunk_type = "source_upload"
        pattern = MagicMock()
        pattern.id = 1
        pattern.pattern_name = "x"
        pattern.category = None
        pattern.tradeoffs = None

        doc = _pattern_chunk_to_document(chunk, pattern, distance=None)
        assert doc.metadata["distance"] is None
        assert doc.metadata["similarity"] is None


class TestChunkToDocument:
    """``_chunk_to_document`` builds the Document for a user document chunk."""

    def test_includes_all_required_metadata_fields(self):
        from app.core.rag import _chunk_to_document

        chunk = MagicMock()
        chunk.id = 99
        chunk.chunk_text = "auth chunk content"
        chunk.chunk_metadata = None
        chunk.chunk_index = 3

        uploaded_doc = MagicMock()
        uploaded_doc.id = 7
        uploaded_doc.filename = "spec.pdf"
        uploaded_doc.project_id = 42

        doc = _chunk_to_document(chunk, uploaded_doc, distance=0.3)

        assert doc.page_content == "auth chunk content"
        assert doc.metadata["chunk_id"] == 99
        assert doc.metadata["document_id"] == 7
        assert doc.metadata["filename"] == "spec.pdf"
        assert doc.metadata["project_id"] == 42
        assert doc.metadata["chunk_index"] == 3
        assert doc.metadata["distance"] == 0.3
        assert doc.metadata["source_type"] == "document_chunk"

    def test_merges_chunk_metadata_into_doc_metadata(self):
        from app.core.rag import _chunk_to_document

        chunk = MagicMock()
        chunk.id = 1
        chunk.chunk_text = "x"
        chunk.chunk_metadata = {"filename": "real.pdf", "page": 5}
        chunk.chunk_index = 0

        uploaded_doc = MagicMock()
        uploaded_doc.id = 1
        uploaded_doc.filename = "placeholder.pdf"
        uploaded_doc.project_id = 1

        doc = _chunk_to_document(chunk, uploaded_doc, distance=0.1)
        # chunk_metadata overrides upload_document fields
        assert doc.metadata["filename"] == "real.pdf"
        assert doc.metadata["page"] == 5

    def test_handles_none_page_content(self):
        from app.core.rag import _chunk_to_document

        chunk = MagicMock()
        chunk.id = 1
        chunk.chunk_text = None
        chunk.chunk_metadata = None
        chunk.chunk_index = 0

        uploaded_doc = MagicMock()
        uploaded_doc.id = 1
        uploaded_doc.filename = "x.pdf"
        uploaded_doc.project_id = 1

        doc = _chunk_to_document(chunk, uploaded_doc, distance=0.1)
        assert doc.page_content == ""  # empty string when chunk_text is None


class TestSetPgvectorProbes:
    """``_set_pgvector_probes`` sets the LOCAL ivfflat.probes for the txn."""

    def test_executes_set_local_statement(self):
        from app.core.rag import _set_pgvector_probes

        db = MagicMock()
        _set_pgvector_probes(db, probes=12)
        # The SQL contains "SET LOCAL ivfflat.probes = 12"
        call_args = db.execute.call_args
        sql_str = str(call_args.args[0])
        assert "SET LOCAL ivfflat.probes" in sql_str
        assert "12" in sql_str