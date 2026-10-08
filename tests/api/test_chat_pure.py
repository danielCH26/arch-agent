"""Tests para app.api.chat — helpers puros + ``ChatRequest`` model."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestIsRelevant:
    """``_is_relevant`` returns True when similarity >= RAG_MIN_SIMILARITY."""

    def test_returns_true_above_threshold(self):
        from app.api.chat import _is_relevant, RAG_MIN_SIMILARITY

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY + 0.1}
        assert _is_relevant(doc) is True

    def test_returns_true_at_threshold(self):
        from app.api.chat import _is_relevant, RAG_MIN_SIMILARITY

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY}
        assert _is_relevant(doc) is True

    def test_returns_false_below_threshold(self):
        from app.api.chat import _is_relevant, RAG_MIN_SIMILARITY

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY - 0.1}
        assert _is_relevant(doc) is False

    def test_treats_missing_similarity_as_zero(self):
        from app.api.chat import _is_relevant

        doc = MagicMock()
        doc.metadata = {}
        assert _is_relevant(doc) is False

    def test_treats_none_similarity_as_zero(self):
        from app.api.chat import _is_relevant

        doc = MagicMock()
        doc.metadata = {"similarity": None}
        assert _is_relevant(doc) is False


class TestIsNearMiss:
    """``_is_near_miss``: window between (threshold - margin) and threshold."""

    def test_returns_true_in_near_miss_window(self):
        from app.api.chat import _is_near_miss, RAG_MIN_SIMILARITY, RAG_NEAR_MISS_MARGIN

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY - 0.01}
        assert _is_near_miss(doc) is True

        doc.metadata = {"similarity": RAG_MIN_SIMILARITY - RAG_NEAR_MISS_MARGIN}
        assert _is_near_miss(doc) is True

    def test_returns_false_above_threshold(self):
        from app.api.chat import _is_near_miss, RAG_MIN_SIMILARITY

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY + 0.1}
        assert _is_near_miss(doc) is False

    def test_returns_false_below_window(self):
        from app.api.chat import _is_near_miss, RAG_MIN_SIMILARITY, RAG_NEAR_MISS_MARGIN

        doc = MagicMock()
        doc.metadata = {"similarity": RAG_MIN_SIMILARITY - RAG_NEAR_MISS_MARGIN - 0.1}
        assert _is_near_miss(doc) is False

    def test_treats_missing_similarity_as_below_window(self):
        from app.api.chat import _is_near_miss

        doc = MagicMock()
        doc.metadata = {}
        assert _is_near_miss(doc) is False


class TestIsDiagramTurn:
    """``_is_diagram_turn`` detects diagram requests via phase or message."""

    def test_returns_true_when_project_phase_is_refinamiento(self):
        from app.api.chat import _is_diagram_turn

        project = MagicMock()
        project.current_phase = "refinamiento"
        assert _is_diagram_turn(project, "anything") is True

    def test_returns_true_when_project_phase_is_diagram(self):
        from app.api.chat import _is_diagram_turn

        project = MagicMock()
        project.current_phase = "diagram"
        assert _is_diagram_turn(project, "anything") is True

    def test_returns_true_when_project_phase_is_diagrama(self):
        from app.api.chat import _is_diagram_turn

        project = MagicMock()
        project.current_phase = "diagrama"
        assert _is_diagram_turn(project, "anything") is True

    def test_returns_true_when_message_mentions_diagram_word(self):
        from app.api.chat import _is_diagram_turn

        assert _is_diagram_turn(None, "muéstrame un diagrama de la arquitectura") is True

    def test_returns_true_when_message_mentions_mermaid(self):
        from app.api.chat import _is_diagram_turn

        assert _is_diagram_turn(None, "Genera un mermaid del flujo") is True

    def test_returns_true_when_message_mentions_flowchart(self):
        from app.api.chat import _is_diagram_turn

        assert _is_diagram_turn(None, "Necesito un flowchart") is True

    def test_word_boundary_protection_against_paragraph(self):
        """Regression: 'paragraph' used to match 'graph' substring, triggering
        false positives. With word-boundary regex it should NOT match."""
        from app.api.chat import _is_diagram_turn

        assert _is_diagram_turn(None, "write me a paragraph of text") is False
        assert _is_diagram_turn(None, "photograph the scene") is False

    def test_returns_false_for_unrelated_message_and_phase(self):
        from app.api.chat import _is_diagram_turn

        project = MagicMock()
        project.current_phase = "requerimientos"
        assert _is_diagram_turn(project, "What is the weather today?") is False

    def test_returns_false_for_none_project_and_empty_message(self):
        from app.api.chat import _is_diagram_turn

        assert _is_diagram_turn(None, "") is False


class TestRagConstantsInChat:
    """Verify chat.py RAG constants are reasonable."""

    def test_rag_min_similarity_is_in_zero_to_one(self):
        from app.api.chat import RAG_MIN_SIMILARITY

        assert 0 < RAG_MIN_SIMILARITY <= 1.0

    def test_near_miss_margin_is_positive(self):
        from app.api.chat import RAG_NEAR_MISS_MARGIN, RAG_MIN_SIMILARITY

        assert RAG_NEAR_MISS_MARGIN > 0
        assert RAG_MIN_SIMILARITY - RAG_NEAR_MISS_MARGIN < RAG_MIN_SIMILARITY

    def test_diagram_phases_include_refinamiento(self):
        from app.api.chat import DIAGRAM_PHASES

        assert "refinamiento" in DIAGRAM_PHASES
        assert "diagram" in DIAGRAM_PHASES

    def test_proposal_phases_include_propuesta(self):
        from app.api.chat import PROPOSAL_PHASES

        assert "propuesta" in PROPOSAL_PHASES


class TestChatRequestModel:
    """Tests de Pydantic model ``ChatRequest``."""

    def test_minimal_request(self):
        from app.api.chat import ChatRequest

        r = ChatRequest(message="hi")
        assert r.message == "hi"
        assert r.project_id is None
        assert r.display_message is None

    def test_full_request(self):
        from app.api.chat import ChatRequest

        r = ChatRequest(
            project_id=5,
            message="Show me a hexagonal architecture",
            display_message="hexagonal architecture",
        )
        assert r.project_id == 5
        assert r.message == "Show me a hexagonal architecture"
        assert r.display_message == "hexagonal architecture"

    def test_display_message_optional_separate_from_message(self):
        """``display_message`` is the user-typed text; ``message`` is the
        technical prompt. They can differ for 'Solicitar cambios' on a diagram.
        """
        from app.api.chat import ChatRequest

        r = ChatRequest(
            project_id=5,
            message="[technical prompt with mermaid block] Add a database",
            display_message="Add a database",
        )
        assert r.message != r.display_message
        assert r.display_message == "Add a database"


class TestSyntheticRagDocument:
    """``SyntheticRagDocument`` is a frozen dataclass that mimics a Document."""

    def test_stores_page_content_and_metadata(self):
        from app.api.chat import SyntheticRagDocument

        doc = SyntheticRagDocument(
            page_content="Hexagonal architecture",
            metadata={"source_type": "architect_pattern", "pattern_id": 7},
        )
        assert doc.page_content == "Hexagonal architecture"
        assert doc.metadata == {"source_type": "architect_pattern", "pattern_id": 7}

    def test_metadata_can_contain_arbitrary_keys(self):
        from app.api.chat import SyntheticRagDocument

        doc = SyntheticRagDocument(
            page_content="x",
            metadata={"score": 0.95, "tags": ["hexagonal", "ports"]},
        )
        assert doc.metadata["score"] == 0.95
        assert doc.metadata["tags"] == ["hexagonal", "ports"]

    def test_handles_none_page_content(self):
        from app.api.chat import SyntheticRagDocument

        doc = SyntheticRagDocument(
            page_content=None,
            metadata={"x": 1},
        )
        assert doc.page_content is None
        assert doc.metadata == {"x": 1}


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