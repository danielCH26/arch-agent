"""Tests para /api/patterns/* — list y source-chunks."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch


@contextmanager
def _client(db_mock):
    """Yield TestClient with auth override + DB mock."""
    from fastapi.testclient import TestClient
    from server import app
    from app.api.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1,
        "username": "laura",
        "jti": None,
    }
    with patch("app.api.patterns.SessionLocal") as mock_session:
        mock_session.return_value = db_mock
        client = TestClient(app, raise_server_exceptions=False)
        try:
            yield client, db_mock
        finally:
            app.dependency_overrides.clear()


class TestListPatternsEndpoint:
    """Integration tests for GET /api/patterns."""

    def test_returns_patterns_paginated(self):
        p1 = MagicMock()
        p1.id = 1
        p1.pattern_name = "Microservicios"
        p1.category = "Distribuida"
        p1.description = "Servicios independientes"
        p1.use_cases = "Sistemas grandes"
        p1.tradeoffs = {"complexity": "alta"}
        p1.when_not_to_use = "Sistemas pequeños"
        p2 = MagicMock()
        p2.id = 2
        p2.pattern_name = "Monolito"
        p2.category = "Monolítica"
        p2.description = "Una sola unidad"
        p2.use_cases = "Sistemas pequeños"
        p2.tradeoffs = {"scaling": "limitado"}
        p2.when_not_to_use = "Equipos grandes"

        db = MagicMock()
        # The query chain: .query().order_by() — both count() and .offset().limit().all()
        db.query.return_value.order_by.return_value.count.return_value = 2
        db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [p1, p2]

        with _client(db) as (client, _):
            resp = client.get("/api/patterns")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert body["items"][0]["pattern_name"] == "Microservicios"
        assert body["items"][1]["category"] == "Monolítica"

    def test_returns_empty_list_when_no_patterns(self):
        db = MagicMock()
        db.query.return_value.order_by.return_value.count.return_value = 0
        db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        with _client(db) as (client, _):
            resp = client.get("/api/patterns")

        assert resp.status_code == 200
        assert resp.json() == {"total": 0, "items": []}

    def test_respects_limit_and_offset(self):
        db = MagicMock()
        db.query.return_value.order_by.return_value.count.return_value = 50
        db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        with _client(db) as (client, _):
            resp = client.get("/api/patterns?limit=10&offset=20")

        assert resp.status_code == 200
        # Verify the chain was called with the correct limit/offset
        offset_call = db.query.return_value.order_by.return_value.offset
        offset_call.assert_called_once_with(20)
        offset_call.return_value.limit.assert_called_once_with(10)


class TestListPatternSourceChunksEndpoint:
    """Integration tests for GET /api/patterns/{id}/source-chunks."""

    def test_returns_404_when_pattern_missing(self):
        db = MagicMock()
        # exists query: returns None
        db.query.return_value.filter.return_value.first.return_value = None

        with _client(db) as (client, _):
            resp = client.get("/api/patterns/999/source-chunks")

        assert resp.status_code == 404
        assert "no encontrado" in resp.json()["detail"]

    def test_returns_source_chunks_when_pattern_exists(self):
        db = MagicMock()
        # exists query returns tuple-like row (id,); any truthy means exists
        db.query.return_value.filter.return_value.first.return_value = (42,)

        chunk = MagicMock()
        chunk.id = 100
        chunk.chunk_type = "source_upload"
        chunk.chunk_text = "Chunk text from uploaded source."
        chunk.chunk_metadata = {"source": "ingest_pattern_source.py"}

        with (
            _client(db) as (client, _),
            patch(
                "app.api.patterns.get_pattern_source_chunks",
                return_value=[chunk],
            ) as mock_get,
        ):
            resp = client.get("/api/patterns/42/source-chunks")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["chunk_type"] == "source_upload"
        assert body[0]["chunk_metadata"]["source"] == "ingest_pattern_source.py"
        mock_get.assert_called_once_with(42)

    def test_returns_empty_list_when_no_chunks(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = (1,)

        with (
            _client(db) as (client, _),
            patch("app.api.patterns.get_pattern_source_chunks", return_value=[]),
        ):
            resp = client.get("/api/patterns/1/source-chunks")

        assert resp.status_code == 200
        assert resp.json() == []


class TestPatternModels:
    """Tests de Pydantic models de patterns."""

    def test_pattern_out_full(self):
        from app.api.patterns import PatternOut

        p = PatternOut(
            id=1,
            pattern_name="Hexagonal",
            category="Arquitectura",
            description="Ports & adapters",
            use_cases="Clean separation",
            tradeoffs={"testability": "high"},
            when_not_to_use="Simple CRUD",
        )
        assert p.id == 1
        assert p.tradeoffs == {"testability": "high"}

    def test_pattern_out_optional_fields(self):
        from app.api.patterns import PatternOut

        p = PatternOut(id=1, pattern_name="X", category=None, description=None, use_cases=None, tradeoffs=None, when_not_to_use=None)
        assert p.category is None
        assert p.tradeoffs is None

    def test_pattern_list_out(self):
        from app.api.patterns import PatternListOut, PatternOut

        lst = PatternListOut(
            total=1,
            items=[PatternOut(
                id=1,
                pattern_name="Microservicios",
                category=None,
                description=None,
                use_cases=None,
                tradeoffs=None,
                when_not_to_use=None,
            )],
        )
        assert lst.total == 1
        assert lst.items[0].pattern_name == "Microservicios"

    def test_pattern_source_chunk_out(self):
        from app.api.patterns import PatternSourceChunkOut

        c = PatternSourceChunkOut(
            id=1,
            chunk_type="source_upload",
            chunk_text="text",
            chunk_metadata={"a": 1},
        )
        assert c.chunk_type == "source_upload"