"""
Tests para el selector dinámico de modelos (HU12).

Issue: #7 - HU12 Configuración de LLM

Tests para la lógica pura de filtrado (sin Chainlit).
"""

import pytest

from app.core.llm_model_selector import (
    filter_models,
    split_visible_and_excess,
    match_model_exact,
    is_filter_refinement,
    MAX_BUTTONS,
)


# Modelos típicos para tests
SAMPLE_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
    "gpt-3.5-turbo-16k",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
    "text-embedding-3-small",
    "text-embedding-3-large",
    "dall-e-3",
    "babbage-002",
]


class TestFilterModels:
    """Tests de filter_models()."""

    def test_empty_filter_returns_all(self):
        assert filter_models(SAMPLE_MODELS, "") == SAMPLE_MODELS

    def test_whitespace_filter_returns_all(self):
        assert filter_models(SAMPLE_MODELS, "   ") == SAMPLE_MODELS

    def test_exact_match_single(self):
        # "gpt-4o" matchea tanto "gpt-4o" como "gpt-4o-mini" (substring)
        result = filter_models(SAMPLE_MODELS, "gpt-4o")
        assert "gpt-4o" in result
        assert "gpt-4o-mini" in result

    def test_partial_match_multiple(self):
        result = filter_models(SAMPLE_MODELS, "gpt")
        assert len(result) == 5
        assert all("gpt" in m.lower() for m in result)

    def test_case_insensitive(self):
        result_lower = filter_models(SAMPLE_MODELS, "gpt")
        result_upper = filter_models(SAMPLE_MODELS, "GPT")
        result_mixed = filter_models(SAMPLE_MODELS, "Gpt")
        assert result_lower == result_upper == result_mixed

    def test_no_match_returns_empty(self):
        assert filter_models(SAMPLE_MODELS, "xyz123") == []

    def test_substring_in_middle(self):
        result = filter_models(SAMPLE_MODELS, "turbo")
        assert "gpt-4-turbo" in result
        assert "gpt-3.5-turbo" in result
        assert "gpt-3.5-turbo-16k" in result
        assert len(result) == 3

    def test_filter_preserves_order(self):
        result = filter_models(SAMPLE_MODELS, "gpt")
        # Debe mantener el orden original
        assert result == [m for m in SAMPLE_MODELS if "gpt" in m.lower()]

    def test_filter_with_many_results(self):
        # "model-0" matchea todos los modelos que tienen "model-0" en el nombre
        # (model-000, model-001, ..., model-099) = 100 modelos
        many_models = [f"model-{i:03d}" for i in range(100)]
        result = filter_models(many_models, "model-0")
        assert len(result) == 100

    def test_filter_unique_substring(self):
        # "model-00" matchea solo model-000 a model-009 = 10 modelos
        many_models = [f"model-{i:03d}" for i in range(100)]
        result = filter_models(many_models, "model-00")
        assert len(result) == 10  # model-000 a model-009

    def test_filter_with_special_chars(self):
        models = ["model-v1.0", "model-v2.0", "other"]
        result = filter_models(models, "v1")
        assert result == ["model-v1.0"]


class TestSplitVisibleAndExcess:
    """Tests de split_visible_and_excess()."""

    def test_no_excess_when_under_limit(self):
        visible, excess = split_visible_and_excess(SAMPLE_MODELS[:10])
        assert visible == SAMPLE_MODELS[:10]
        assert excess == 0

    def test_no_excess_at_exact_limit(self):
        visible, excess = split_visible_and_excess(SAMPLE_MODELS, max_visible=12)
        assert len(visible) == 12
        assert excess == 0

    def test_excess_above_limit(self):
        visible, excess = split_visible_and_excess(SAMPLE_MODELS, max_visible=5)
        assert len(visible) == 5
        assert excess == 7  # 12 - 5

    def test_custom_max_visible(self):
        visible, excess = split_visible_and_excess(SAMPLE_MODELS, max_visible=3)
        assert len(visible) == 3
        assert excess == 9

    def test_empty_list(self):
        visible, excess = split_visible_and_excess([])
        assert visible == []
        assert excess == 0

    def test_returns_copy_not_reference(self):
        original = SAMPLE_MODELS.copy()
        visible, _ = split_visible_and_excess(original)
        visible.append("MODIFIED")
        # El original no debe cambiar
        assert "MODIFIED" not in original


class TestMatchModelExact:
    """Tests de match_model_exact()."""

    def test_exact_match(self):
        assert match_model_exact(SAMPLE_MODELS, "gpt-4o") == "gpt-4o"

    def test_case_insensitive_match(self):
        assert match_model_exact(SAMPLE_MODELS, "GPT-4O") == "gpt-4o"

    def test_no_match_returns_none(self):
        assert match_model_exact(SAMPLE_MODELS, "xyz") is None

    def test_partial_match_returns_none(self):
        # "gpt" no es match exacto
        assert match_model_exact(SAMPLE_MODELS, "gpt") is None

    def test_empty_input_returns_none(self):
        assert match_model_exact(SAMPLE_MODELS, "") is None

    def test_whitespace_only_returns_none(self):
        assert match_model_exact(SAMPLE_MODELS, "   ") is None

    def test_match_with_whitespace_in_input(self):
        # Debe hacer strip antes de comparar
        assert match_model_exact(SAMPLE_MODELS, "  gpt-4o  ") == "gpt-4o"


class TestIsFilterRefinement:
    """Tests de is_filter_refinement()."""

    def test_exact_match_is_not_refinement(self):
        assert is_filter_refinement("gpt-4o", SAMPLE_MODELS) is False

    def test_partial_match_is_refinement(self):
        # "gpt" matchea varios modelos → es refinamiento
        assert is_filter_refinement("gpt", SAMPLE_MODELS) is True

    def test_no_match_is_not_refinement(self):
        assert is_filter_refinement("xyz123", SAMPLE_MODELS) is False

    def test_empty_input_is_not_refinement(self):
        assert is_filter_refinement("", SAMPLE_MODELS) is False

    def test_substring_match_is_refinement(self):
        assert is_filter_refinement("turbo", SAMPLE_MODELS) is True

    def test_case_insensitive(self):
        assert is_filter_refinement("GPT", SAMPLE_MODELS) is True
        assert is_filter_refinement("gpt", SAMPLE_MODELS) is True


class TestIntegrationScenarios:
    """Tests de escenarios completos del flujo de filtrado."""

    def test_empty_filter_shows_all_within_limit(self):
        # Simular flujo: usuario deja vacío → ve todos
        filtered = filter_models(SAMPLE_MODELS, "")
        visible, excess = split_visible_and_excess(filtered)
        assert visible == SAMPLE_MODELS
        assert excess == 0

    def test_filter_shows_subset(self):
        # Simular: usuario escribe "claude"
        filtered = filter_models(SAMPLE_MODELS, "claude")
        visible, excess = split_visible_and_excess(filtered)
        assert len(visible) == 3
        assert all("claude" in m.lower() for m in visible)
        assert excess == 0

    def test_filter_with_many_results_shows_excess(self):
        # Simular: usuario tiene 30 modelos, filtra "model" → 30 resultados
        many = [f"model-{i:03d}" for i in range(30)]
        filtered = filter_models(many, "model")
        visible, excess = split_visible_and_excess(filtered)
        assert len(visible) == MAX_BUTTONS
        assert excess == 10  # 30 - 20

    def test_refinement_flow(self):
        """Simula el flujo completo de refinamiento."""
        # 1. Usuario filtra "gpt" → 5 resultados
        step1 = filter_models(SAMPLE_MODELS, "gpt")
        assert len(step1) == 5

        # 2. Refina con "gpt-4" → 3 resultados (gpt-4o, gpt-4o-mini, gpt-4-turbo)
        step2 = filter_models(SAMPLE_MODELS, "gpt-4")
        assert len(step2) == 3

        # 3. Selecciona "gpt-4o" → match exacto
        selected = match_model_exact(SAMPLE_MODELS, "gpt-4o")
        assert selected == "gpt-4o"

    def test_invalid_input_keeps_options_open(self):
        """Si el input no matchea nada, debe volver a pedir."""
        # 1. Filtra "xyz" → vacío
        result = filter_models(SAMPLE_MODELS, "xyz")
        assert result == []

        # 2. match_model_exact con "xyz" → None
        assert match_model_exact(SAMPLE_MODELS, "xyz") is None

        # 3. is_filter_refinement con "xyz" → False
        assert is_filter_refinement("xyz", SAMPLE_MODELS) is False
