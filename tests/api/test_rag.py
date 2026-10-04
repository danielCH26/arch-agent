from unittest.mock import patch

import asyncio
import pytest
from langchain_core.documents import Document


class TestRAGApiModels:
    def test_search_request_defaults_to_all_scope(self):
        from app.api.rag import RAGSearchRequest

        request = RAGSearchRequest(query="microservicios")

        assert request.query == "microservicios"
        assert request.scope == "all"
        assert request.k == 5

    def test_search_request_rejects_empty_query(self):
        from app.api.rag import RAGSearchRequest

        with pytest.raises(ValueError):
            RAGSearchRequest(query="")


class TestRAGApi:
    @patch("app.api.rag.similarity_search")
    def test_search_rag_returns_langchain_documents_as_response(self, mock_search):
        from app.api.rag import RAGSearchRequest, search_rag

        mock_search.return_value = (
            [
                Document(
                    page_content="Arquitectura de microservicios",
                    metadata={"source_type": "architect_pattern", "distance": 0.1},
                )
            ],
            {"search_ms": 7.123, "embedding_ms": 18.456, "total_ms": 25.579},
        )

        response = asyncio.run(
            search_rag(
                body=RAGSearchRequest(query="servicios independientes", project_id=9),
                current_user={"user_id": 3, "username": "laura", "jti": None},
            )
        )

        mock_search.assert_called_once_with(
            query="servicios independientes",
            user_id=3,
            project_id=9,
            k=5,
            scope="all",
            category=None,
        )
        assert response.results[0].content == "Arquitectura de microservicios"
        assert response.results[0].metadata["source_type"] == "architect_pattern"
        assert response.search_ms == 7.12
        assert response.total_ms == 25.58


class TestRAGCoreHelpers:
    def test_merge_by_distance_orders_closest_first(self):
        from app.core.rag import _merge_by_distance

        far = Document(page_content="far", metadata={"distance": 0.8})
        close = Document(page_content="close", metadata={"distance": 0.1})
        mid = Document(page_content="mid", metadata={"distance": 0.4})

        result = _merge_by_distance([([far, close], 2.0), ([mid], 1.0)])

        assert [doc.page_content for doc in result] == ["close", "mid", "far"]

    def test_validate_embedding_requires_384_dimensions(self):
        from app.core.rag import RAGSearchError, _validate_embedding

        _validate_embedding([0.1] * 384)
        with pytest.raises(RAGSearchError, match="384 dimensiones"):
            _validate_embedding([0.1] * 383)

    def test_reuses_cached_query_embedding_without_caching_search_results(self, monkeypatch):
        """Una consulta repetida evita el modelo, pero ambas búsquedas siguen a DB."""
        from app.core import rag

        rag.clear_embedding_cache()
        monkeypatch.setattr(rag, "_EMBEDDING_CACHE_SIZE", 2)
        model = type("Embeddings", (), {"embed_query": lambda self, _: [0.1] * 384})()
        calls = {"patterns": 0, "documents": 0}

        def patterns(*_args, **_kwargs):
            calls["patterns"] += 1
            return [], 4.0

        def documents(*_args, **_kwargs):
            calls["documents"] += 1
            return [], 5.0

        monkeypatch.setattr(rag, "get_embeddings", lambda: model)
        monkeypatch.setattr(rag, "similarity_search_patterns_by_vector", patterns)
        monkeypatch.setattr(rag, "similarity_search_document_chunks_by_vector", documents)

        _, first = rag.similarity_search("consulta frecuente", user_id=7, scope="all")
        _, second = rag.similarity_search("consulta frecuente", user_id=7, scope="all")

        assert first["embedding_cached"] is False
        assert second["embedding_cached"] is True
        assert calls == {"patterns": 2, "documents": 2}

    def test_parallel_search_uses_slowest_branch_as_wall_clock_metric(self, monkeypatch):
        from app.core import rag

        rag.clear_embedding_cache()
        monkeypatch.setattr(rag, "get_embeddings", lambda: type("E", (), {"embed_query": lambda *_: [0.1] * 384})())
        monkeypatch.setattr(rag, "similarity_search_patterns_by_vector", lambda *_args, **_kwargs: ([], 11.0))
        monkeypatch.setattr(rag, "similarity_search_document_chunks_by_vector", lambda *_args, **_kwargs: ([], 23.0))

        _, metrics = rag.similarity_search("latencia", user_id=7, scope="all")

        assert metrics["search_ms"] == 23.0
