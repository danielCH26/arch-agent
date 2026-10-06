"""Tests para app.core.rag — pure helpers + similarity_search validation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestValidateEmbedding:
    """``_validate_embedding`` rejects wrong dimensions before DB query."""

    def test_passes_for_384_dim_embedding(self):
        from app.core.rag import _validate_embedding

        _validate_embedding([0.1] * 384)  # should not raise

    def test_raises_for_short_embedding(self):
        from app.core.rag import _validate_embedding, RAGSearchError

        with pytest.raises(RAGSearchError, match="384"):
            _validate_embedding([0.1] * 100)

    def test_raises_for_long_embedding(self):
        from app.core.rag import _validate_embedding, RAGSearchError

        with pytest.raises(RAGSearchError, match="384"):
            _validate_embedding([0.1] * 500)

    def test_raises_for_empty_embedding(self):
        from app.core.rag import _validate_embedding, RAGSearchError

        with pytest.raises(RAGSearchError, match="384"):
            _validate_embedding([])


class TestSimilarityFromCosineDistance:
    def test_returns_none_for_none_input(self):
        from app.core.rag import _similarity_from_cosine_distance

        assert _similarity_from_cosine_distance(None) is None

    def test_converts_distance_to_similarity(self):
        from app.core.rag import _similarity_from_cosine_distance

        # cosine distance 0.2 → similarity 0.8
        assert _similarity_from_cosine_distance(0.2) == pytest.approx(0.8)

    def test_zero_distance_is_full_similarity(self):
        from app.core.rag import _similarity_from_cosine_distance

        assert _similarity_from_cosine_distance(0.0) == 1.0

    def test_handles_distance_of_one(self):
        from app.core.rag import _similarity_from_cosine_distance

        # distance 1 → similarity 0
        assert _similarity_from_cosine_distance(1.0) == pytest.approx(0.0)


class TestMergeByDistance:
    def test_merges_multiple_groups_sorted_by_distance_ascending(self):
        from app.core.rag import _merge_by_distance

        doc1 = MagicMock()
        doc1.metadata = {"distance": 0.1}
        doc2 = MagicMock()
        doc2.metadata = {"distance": 0.5}
        doc3 = MagicMock()
        doc3.metadata = {"distance": 0.3}
        doc4 = MagicMock()
        doc4.metadata = {"distance": 0.7}

        group_a = ([doc1, doc4], 100.0)  # distances 0.1, 0.7
        group_b = ([doc2, doc3], 50.0)  # distances 0.5, 0.3

        merged = _merge_by_distance([group_a, group_b])

        # All 4 docs present, sorted by distance ascending
        assert len(merged) == 4
        assert [d.metadata["distance"] for d in merged] == [0.1, 0.3, 0.5, 0.7]

    def test_empty_input_returns_empty_list(self):
        from app.core.rag import _merge_by_distance

        assert _merge_by_distance([]) == []

    def test_handles_none_distance_with_high_sentinel(self):
        from app.core.rag import _merge_by_distance

        doc_no_dist = MagicMock()
        doc_no_dist.metadata = {}  # no "distance" key
        doc_with_dist = MagicMock()
        doc_with_dist.metadata = {"distance": 0.5}

        merged = _merge_by_distance([([doc_no_dist, doc_with_dist], 0.0)])
        # Real distance comes first, None sentinel comes last
        assert merged[0] is doc_with_dist
        assert merged[1] is doc_no_dist

    def test_handles_explicit_none_distance_value(self):
        from app.core.rag import _merge_by_distance

        doc_none = MagicMock()
        doc_none.metadata = {"distance": None}
        doc_real = MagicMock()
        doc_real.metadata = {"distance": 0.2}

        merged = _merge_by_distance([([doc_none, doc_real], 0.0)])
        # Real distance comes first, None sentinel comes last
        assert merged[0] is doc_real
        assert merged[1] is doc_none


class TestSimilaritySearchValidation:
    """similarity_search validation paths that don't require a DB."""

    def test_invalid_scope_raises(self):
        from app.core.rag import similarity_search, RAGSearchError

        with pytest.raises(RAGSearchError, match="scope"):
            similarity_search(
                query="anything",
                scope="invalid",  # type: ignore[arg-type]
                user_id=1,
            )

    def test_documents_scope_without_user_id_raises(self):
        from app.core.rag import similarity_search, RAGSearchError

        with pytest.raises(RAGSearchError, match="user_id"):
            similarity_search(
                query="anything",
                scope="documents",
                user_id=None,
            )

    def test_all_scope_without_user_id_raises(self):
        """scope='all' also requires user_id (because it queries documents too)."""
        from app.core.rag import similarity_search, RAGSearchError

        with pytest.raises(RAGSearchError, match="user_id"):
            similarity_search(
                query="anything",
                scope="all",
                user_id=None,
            )

    def test_patterns_scope_without_user_id_ok(self):
        """scope='patterns' doesn't need user_id (no document queries)."""
        from app.core.rag import similarity_search

        with (
            patch("app.core.rag.get_embeddings") as mock_emb,
            patch("app.core.rag.similarity_search_patterns_by_vector") as mock_ss,
            patch("app.core.rag.similarity_search_document_chunks_by_vector") as mock_doc,
        ):
            mock_emb.return_value.embed_query.return_value = [0.1] * 384
            mock_ss.return_value = ([], 0.0)
            mock_doc.return_value = ([], 0.0)

            docs, metrics = similarity_search(
                query="microkernel",
                scope="patterns",
            )

        # docs is empty because mocks returned empty
        assert docs == []
        assert metrics["search_ms"] == 0.0
        assert metrics["embedding_ms"] >= 0


class TestSimilaritySearchEmptyResults:
    """Empty results are returned as ``([], metrics)`` directly, not raised."""

    def test_empty_results_returns_empty_list(self):
        """Empty results are returned as ``([], metrics)`` directly, not raised.

        With both pattern/doc mocks returning empty lists, similarity_search
        returns ``([], {embedding_ms, search_ms, total_ms})`` — callers can
        continue with no context instead of catching a typed exception.
        """
        from app.core.rag import similarity_search

        with (
            patch("app.core.rag.get_embeddings") as mock_emb,
            patch("app.core.rag.similarity_search_patterns_by_vector") as mock_ss,
            patch("app.core.rag.similarity_search_document_chunks_by_vector") as mock_doc_chunks,
        ):
            mock_emb.return_value.embed_query.return_value = [0.1] * 384
            # Both mocks return empty lists
            mock_ss.return_value = ([], 5.0)
            mock_doc_chunks.return_value = ([], 0.0)

            docs, metrics = similarity_search(
                query="anything",
                user_id=1,
            )

        # Empty list returned, not raised
        assert docs == []
        assert metrics["search_ms"] == 5.0