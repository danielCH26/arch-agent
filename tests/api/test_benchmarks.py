"""
Tests para el endpoint GET /api/llm/benchmarks y el loader JSON.

El endpoint es publico (sin auth) y devuelve la lista de modelos con
score MMLU + thresholds de tier. El frontend debe fetcharlo en lugar
de hardcodear los scores.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.llm_model_benchmarks import (
    LLMBenchmarkFileError,
    load_benchmarks,
)
from server import app


@pytest.fixture
def client():
    return TestClient(app)


# --- Endpoint -----------------------------------------------------------------


class TestBenchmarksEndpoint:
    """GET /api/llm/benchmarks."""

    def test_returns_200_without_auth(self, client):
        """Sin header de Authorization, el endpoint responde 200."""
        response = client.get("/api/llm/benchmarks")
        assert response.status_code == 200

    def test_response_shape(self, client):
        """El shape es {models: [...], tier1_threshold, tier2_threshold}."""
        response = client.get("/api/llm/benchmarks")
        data = response.json()

        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0
        assert data["tier1_threshold"] == 85.0
        assert data["tier2_threshold"] == 60.0

    def test_each_entry_has_required_fields(self, client):
        """Cada model tiene model_id (str), mmlu_score (number) y source."""
        response = client.get("/api/llm/benchmarks")
        data = response.json()

        for entry in data["models"]:
            assert "model_id" in entry
            assert isinstance(entry["model_id"], str)
            assert "mmlu_score" in entry
            assert isinstance(entry["mmlu_score"], (int, float))
            assert 0 <= entry["mmlu_score"] <= 100
            assert "source" in entry
            assert isinstance(entry["source"], str)

    def test_includes_chinese_models(self, client):
        """Los modelos chinos tier 1 (DeepSeek, Qwen) estan en la respuesta."""
        response = client.get("/api/llm/benchmarks")
        data = response.json()
        model_ids = {entry["model_id"] for entry in data["models"]}

        assert "deepseek-v3" in model_ids
        assert "deepseek-r1" in model_ids
        assert "qwen-3-235b-a22b" in model_ids
        assert "qwen-2.5-72b-instruct" in model_ids


# --- Loader --------------------------------------------------------------------


class TestBenchmarksLoader:
    """Validaciones sobre load_benchmarks() directamente."""

    def test_load_returns_non_empty_list(self):
        """El loader devuelve una lista no vacia con el JSON actual."""
        from app.core.llm_model_benchmarks import invalidate_cache
        invalidate_cache()
        entries = load_benchmarks()
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_each_entry_has_required_fields(self):
        from app.core.llm_model_benchmarks import invalidate_cache
        invalidate_cache()
        entries = load_benchmarks()
        for entry in entries:
            assert entry.model_id
            assert isinstance(entry.model_id, str)
            assert isinstance(entry.mmlu_score, float)
            assert 0 <= entry.mmlu_score <= 100
            assert isinstance(entry.source, str)
