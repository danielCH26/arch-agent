"""Tests para app.core.pattern_document_storage — save/get chunks + errors."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestSourceTypeFromFilename:
    """``_source_type_from_filename`` returns the extension as the source type."""

    def test_pdf_extension(self):
        from app.core.pattern_document_storage import _source_type_from_filename

        assert _source_type_from_filename("doc.pdf") == "pdf"
        assert _source_type_from_filename("DOC.PDF") == "pdf"

    def test_md_extension(self):
        from app.core.pattern_document_storage import _source_type_from_filename

        assert _source_type_from_filename("readme.md") == "md"

    def test_unknown_extension_returns_extension_string(self):
        from app.core.pattern_document_storage import _source_type_from_filename

        # For extensions we don't recognize, return the extension itself
        assert _source_type_from_filename("file.txt") == "txt"

    def test_no_extension_returns_unknown(self):
        from app.core.pattern_document_storage import _source_type_from_filename

        assert _source_type_from_filename("filename_no_ext") == "unknown"

    def test_full_path_uses_only_filename_suffix(self):
        from app.core.pattern_document_storage import _source_type_from_filename

        # pathlib.Path suffix only looks at the last segment
        assert _source_type_from_filename("/tmp/dir/doc.pdf") == "pdf"
        assert _source_type_from_filename("a/b/c.md") == "md"


class TestSavePatternChunksValidation:
    """``save_pattern_chunks`` validates inputs before touching the DB."""

    def test_save_chunks_raises_when_lengths_mismatch(self):
        """len(chunks) != len(embeddings) raises PatternStorageError."""
        from app.core.pattern_document_storage import (
            PatternStorageError,
            save_pattern_chunks,
        )

        doc = MagicMock()
        doc.page_content = "anything"
        doc.metadata = {}

        with pytest.raises(PatternStorageError, match="[Mm]ismatch"):
            save_pattern_chunks(
                pattern_id=1,
                chunks=[doc],
                embeddings=[[0.0] * 384, [0.1] * 384],  # two embeddings, one chunk
                filename="x.pdf",
            )

    def test_save_chunks_with_zero_chunks_ok(self):
        """An empty list is fine: returns 0, no DB writes."""
        from app.core.pattern_document_storage import save_pattern_chunks

        result = save_pattern_chunks(
            pattern_id=1,
            chunks=[],
            embeddings=[],
            filename="empty.pdf",
        )
        assert result == 0


class TestGetPatternSourceChunks:
    """``get_pattern_source_chunks`` lists source_upload chunks for a pattern."""

    def test_returns_chunks_for_pattern(self):
        """Lists all source_upload chunks for a given pattern_id."""
        from app.core.pattern_document_storage import get_pattern_source_chunks

        chunk = MagicMock()
        chunk.id = 100
        chunk.chunk_type = "source_upload"
        chunk.chunk_text = "Chunk text from uploaded source."
        chunk.chunk_metadata = None

        with patch("app.core.pattern_document_storage.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [chunk]
            mock_session.return_value = mock_db

            result = get_pattern_source_chunks(pattern_id=1)

        assert len(result) == 1
        assert result[0].id == 100
        mock_db.close.assert_called_once()

    def test_returns_empty_list_when_no_chunks(self):
        from app.core.pattern_document_storage import get_pattern_source_chunks

        with patch("app.core.pattern_document_storage.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            mock_session.return_value = mock_db

            result = get_pattern_source_chunks(pattern_id=1)

        assert result == []
        mock_db.close.assert_called_once()


class TestPatternStorageError:
    def test_is_exception_subclass(self):
        from app.core.pattern_document_storage import PatternStorageError

        assert issubclass(PatternStorageError, Exception)

    def test_can_be_raised_with_args(self):
        from app.core.pattern_document_storage import PatternStorageError

        try:
            raise PatternStorageError("custom message")
        except Exception as e:
            assert isinstance(e, PatternStorageError)
            assert str(e) == "custom message"