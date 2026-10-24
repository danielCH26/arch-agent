"""Tests for app/core/pattern_document_storage.py.

Pure unit tests with full DB mocking (no real database).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from sqlalchemy.exc import IntegrityError

from app.core.pattern_document_storage import (
    PatternStorageError,
    _source_type_from_filename,
    get_pattern_source_chunks,
    save_pattern_chunks,
)


def _make_chunk(text: str) -> Document:
    """Build a minimal langchain Document for tests."""
    return Document(page_content=text, metadata={"source": "test"})


# ---------------------------------------------------------------------------
# _source_type_from_filename
# ---------------------------------------------------------------------------

class TestSourceTypeFromFilename:
    def test_pdf_extension(self):
        assert _source_type_from_filename("guide.pdf") == "pdf"

    def test_markdown_extension(self):
        assert _source_type_from_filename("guide.md") == "md"

    def test_uppercase_extension_is_lowercased(self):
        assert _source_type_from_filename("guide.PDF") == "pdf"
        assert _source_type_from_filename("guide.MD") == "md"

    def test_unknown_extension_returns_text(self):
        assert _source_type_from_filename("guide.xyz") == "xyz"
        assert _source_type_from_filename("guide.txt") == "txt"

    def test_no_extension_returns_unknown(self):
        assert _source_type_from_filename("README") == "unknown"


# ---------------------------------------------------------------------------
# save_pattern_chunks
# ---------------------------------------------------------------------------

class TestSavePatternChunks(unittest.TestCase):
    def _setup_db_mock(self) -> MagicMock:
        """Returns a DB mock where:
        - .get(...) for the pattern existence check returns (1,) i.e. pattern exists
        - .query(ArchitectPattern.id).filter(...).first() returns (1,)
        - .add() accepts anything
        """
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (1,)
        return mock_db

    def test_saves_all_chunks(self):
        chunks = [_make_chunk("chunk 1"), _make_chunk("chunk 2"), _make_chunk("chunk 3")]
        embeddings = [[0.1] * 4, [0.2] * 4, [0.3] * 4]
        mock_db = self._setup_db_mock()

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            inserted = save_pattern_chunks(
                pattern_id=1,
                chunks=chunks,
                embeddings=embeddings,
                filename="guide.pdf",
            )

        assert inserted == 3
        # 3 chunks were added to the session
        assert mock_db.add.call_count == 3
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    def test_stores_filename_and_source_type_in_metadata(self):
        chunks = [_make_chunk("text")]
        embeddings = [[0.1] * 4]
        mock_db = self._setup_db_mock()

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            save_pattern_chunks(
                pattern_id=1,
                chunks=chunks,
                embeddings=embeddings,
                filename="manual.md",
            )

        # Inspect the chunk_metadata arg passed to ArchitectPatternChunk()
        # We mock ArchitectPatternChunk itself by patching the module attribute.
        # Instead we read mock_db.add.call_args to get the constructed record.
        record = mock_db.add.call_args[0][0]
        # ArchitectPatternChunk was called with kwargs; our patched call uses
        # positional args — verify the metadata payload
        assert record.pattern_id == 1
        assert record.chunk_text == "text"
        # chunk_metadata is a dict with filename and source_type
        md = record.chunk_metadata
        assert md["filename"] == "manual.md"
        assert md["source_type"] == "md"

    def test_chunk_type_defaults_to_source_upload(self):
        chunks = [_make_chunk("text")]
        embeddings = [[0.1] * 4]
        mock_db = self._setup_db_mock()

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            save_pattern_chunks(
                pattern_id=1,
                chunks=chunks,
                embeddings=embeddings,
                filename="guide.pdf",
            )

        record = mock_db.add.call_args[0][0]
        assert record.chunk_type == "source_upload"

    def test_custom_chunk_type_overrides_default(self):
        chunks = [_make_chunk("text")]
        embeddings = [[0.1] * 4]
        mock_db = self._setup_db_mock()

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            save_pattern_chunks(
                pattern_id=1,
                chunks=chunks,
                embeddings=embeddings,
                filename="guide.pdf",
                chunk_type="manual_curl",
            )

        record = mock_db.add.call_args[0][0]
        assert record.chunk_type == "manual_curl"

    def test_raises_when_chunks_and_embeddings_count_mismatch(self):
        with self.assertRaises(PatternStorageError) as ctx:
            save_pattern_chunks(
                pattern_id=1,
                chunks=[_make_chunk("a"), _make_chunk("b")],
                embeddings=[[0.1] * 4],
                filename="guide.pdf",
            )

        assert "Mismatch" in str(ctx.exception)
        assert "2 chunks" in str(ctx.exception)
        assert "1 embeddings" in str(ctx.exception)

    def test_raises_when_pattern_does_not_exist(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            with self.assertRaises(PatternStorageError) as ctx:
                save_pattern_chunks(
                    pattern_id=999,
                    chunks=[_make_chunk("a")],
                    embeddings=[[0.1] * 4],
                    filename="guide.pdf",
                )

        assert "pattern_id 999 no existe" in str(ctx.exception)
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()
        # No chunk was added
        mock_db.add.assert_not_called()

    def test_translates_integrity_error_to_storage_error(self):
        mock_db = self._setup_db_mock()
        mock_db.commit.side_effect = IntegrityError("INSERT", {}, Exception("dup"))

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            with self.assertRaises(PatternStorageError) as ctx:
                save_pattern_chunks(
                    pattern_id=1,
                    chunks=[_make_chunk("a")],
                    embeddings=[[0.1] * 4],
                    filename="guide.pdf",
                )

        assert "Constraint violation" in str(ctx.exception)
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_translates_generic_exception_to_storage_error(self):
        mock_db = self._setup_db_mock()
        mock_db.commit.side_effect = RuntimeError("boom")

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            with self.assertRaises(PatternStorageError) as ctx:
                save_pattern_chunks(
                    pattern_id=1,
                    chunks=[_make_chunk("a")],
                    embeddings=[[0.1] * 4],
                    filename="guide.pdf",
                )

        assert "Error al guardar chunks" in str(ctx.exception)
        assert "boom" in str(ctx.exception)
        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    def test_closes_db_on_unexpected_exception(self):
        mock_db = self._setup_db_mock()
        mock_db.commit.side_effect = RuntimeError("kaboom")

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            with self.assertRaises(PatternStorageError):
                save_pattern_chunks(
                    pattern_id=1,
                    chunks=[_make_chunk("a")],
                    embeddings=[[0.1] * 4],
                    filename="guide.pdf",
                )

        mock_db.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_pattern_source_chunks
# ---------------------------------------------------------------------------

class TestGetPatternSourceChunks(unittest.TestCase):
    def test_returns_only_source_upload_typed_chunks(self):
        chunk_a = MagicMock(id=1, chunk_type="source_upload")
        chunk_b = MagicMock(id=2, chunk_type="source_upload")
        mock_db = MagicMock()
        # The query chain: db.query(ArchitectPatternChunk).filter(...).order_by(...).all()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            chunk_a,
            chunk_b,
        ]

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            result = get_pattern_source_chunks(pattern_id=1)

        assert result == [chunk_a, chunk_b]
        mock_db.close.assert_called_once()

    def test_returns_empty_list_when_no_chunks(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            result = get_pattern_source_chunks(pattern_id=42)

        assert result == []
        mock_db.close.assert_called_once()

    def test_closes_db_on_exception(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = (
            RuntimeError("DB down")
        )

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            with self.assertRaises(RuntimeError):
                get_pattern_source_chunks(pattern_id=1)

        mock_db.close.assert_called_once()

    def test_filters_by_pattern_id(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch(
            "app.core.pattern_document_storage.SessionLocal",
            return_value=mock_db,
        ):
            get_pattern_source_chunks(pattern_id=7)

        # .filter(...) is called with TWO predicates: pattern_id and chunk_type.
        # We verify .filter was called exactly once with two positional args.
        mock_db.query.return_value.filter.assert_called_once()
        filter_args, _ = mock_db.query.return_value.filter.call_args
        # BinaryExpression objects: SQLAlchemy builds the SQL, we just verify
        # the right number of predicates were passed.
        assert len(filter_args) == 2
        mock_db.close.assert_called_once()