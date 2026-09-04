"""
Tests para el clasificador de modelos LLM por tier MMLU.

Issue: #51
"""

import pytest

from app.core.model_classifier import (
    ModelClassification,
    classify_model,
    filter_by_tier,
    is_blocked,
)
from app.core.llm_model_benchmarks import (
    MMLU_TIER1_THRESHOLD,
    MMLU_TIER2_THRESHOLD,
    invalidate_cache,
)


@pytest.fixture(autouse=True)
def _bypass_cache():
    """Cada test empieza con cache limpio para que cambios en el YAML tomen efecto."""
    invalidate_cache()
    yield
    invalidate_cache()


class TestClassifyModel:
    """Tests de classify_model con los 4 tiers."""

    def test_tier1_when_score_at_threshold(self):
        # gpt-4o: 88.7 (>= 85 = tier1)
        result = classify_model("gpt-4o")
        assert result.tier == "tier1"
        assert result.mmlu_score == 88.7
        assert result.source is not None

    def test_tier1_o_series(self):
        # o1: 92.3 (>= 85)
        result = classify_model("o1")
        assert result.tier == "tier1"
        assert result.mmlu_score == 92.3

    def test_tier1_anthropic_sonnet_4(self):
        # claude-sonnet-4: 91.5
        result = classify_model("claude-sonnet-4")
        assert result.tier == "tier1"

    def test_tier1_minimax_m3(self):
        # MiniMax-M3: 87.0
        result = classify_model("MiniMax-M3")
        assert result.tier == "tier1"
        assert result.mmlu_score == 87.0

    def test_tier2_when_score_below_threshold(self):
        # gpt-4o-mini: 82.0 (60-85 = tier2)
        result = classify_model("gpt-4o-mini")
        assert result.tier == "tier2"
        assert result.mmlu_score == 82.0

    def test_tier2_at_lower_boundary(self):
        # claude-3-5-haiku: 75.2
        result = classify_model("claude-3-5-haiku")
        assert result.tier == "tier2"

    def test_blocked_when_score_below_60(self):
        # gpt-3.5-turbo: 57.0 (< 60 = blocked)
        result = classify_model("gpt-3.5-turbo")
        assert result.tier == "blocked"
        assert result.mmlu_score == 57.0

    def test_blocked_llama_8b(self):
        # llama-3.1-8b-instruct: 56.3
        result = classify_model("llama-3.1-8b-instruct")
        assert result.tier == "blocked"

    def test_unknown_when_model_not_in_yaml(self):
        result = classify_model("some-brand-new-model-2026")
        assert result.tier == "unknown"
        assert result.mmlu_score is None
        assert result.source is None

    def test_empty_string_returns_unknown(self):
        result = classify_model("")
        assert result.tier == "unknown"

    def test_case_sensitive_lookup(self):
        # YAML tiene "gpt-4o" lowercase, no es case-insensitive
        result = classify_model("GPT-4O")
        assert result.tier == "unknown"


class TestFilterByTier:
    """Tests de la partición por tier."""

    def test_partitions_correctly(self):
        model_ids = [
        "gpt-4o",              # tier1
        "gpt-4o-mini",         # tier2
        "gpt-3.5-turbo",       # blocked
        "future-model",        # unknown
        "claude-sonnet-4",     # tier1
        ]
        buckets = filter_by_tier(model_ids)

        assert buckets["tier1"] == ["gpt-4o", "claude-sonnet-4"]
        assert "gpt-4o-mini" in buckets["unknown_or_tier2"]
        assert "future-model" in buckets["unknown_or_tier2"]
        assert buckets["blocked"] == ["gpt-3.5-turbo"]

    def test_empty_input(self):
        assert filter_by_tier([]) == {
            "tier1": [],
            "unknown_or_tier2": [],
            "blocked": [],
        }

    def test_all_blocked(self):
        result = filter_by_tier(["gpt-3.5-turbo", "llama-3.1-8b-instruct"])
        assert result["tier1"] == []
        assert result["unknown_or_tier2"] == []
        assert len(result["blocked"]) == 2

    def test_preserves_input_order(self):
        model_ids = ["claude-sonnet-4", "gpt-4o", "o1"]
        result = filter_by_tier(model_ids)
        # El orden del input se preserva dentro de cada bucket
        assert result["tier1"] == ["claude-sonnet-4", "gpt-4o", "o1"]


class TestIsBlocked:
    """Tests del shortcut is_blocked."""

    def test_blocked_model_returns_true(self):
        assert is_blocked("gpt-3.5-turbo") is True

    def test_tier1_returns_false(self):
        assert is_blocked("gpt-4o") is False

    def test_unknown_returns_false(self):
        # Unknown NO es blocked — aparece con warning, no se oculta
        assert is_blocked("some-unknown-model") is False

    def test_tier2_returns_false(self):
        assert is_blocked("gpt-4o-mini") is False


class TestThresholds:
    """Smoke test de los thresholds (no deberian cambiar sin querer)."""

    def test_tier1_threshold(self):
        assert MMLU_TIER1_THRESHOLD == 85.0

    def test_tier2_threshold(self):
        assert MMLU_TIER2_THRESHOLD == 60.0