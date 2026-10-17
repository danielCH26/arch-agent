"""Tests for app/core/llm_model_benchmarks.py.

Covers the YAML loading and score lookup with full mocking.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, mock_open, patch


# ---------------------------------------------------------------------------
# Tests that need to import the module's symbols
# ---------------------------------------------------------------------------


class TestLoadBenchmarks(unittest.TestCase):
    """load_benchmarks reads a YAML file and caches the result."""

    def _reload_module(self):
        # Force re-import so module-level cache resets between tests
        import importlib
        import app.core.llm_model_benchmarks as bm
        importlib.reload(bm)
        return bm

    def test_loads_yaml_into_benchmark_entries(self):
        yaml_content = (
            "tiers:\n"
            "  tier1:\n"
            "    - model_id: gpt-4\n"
            "      score: 95\n"
            "  tier2:\n"
            "    - model_id: gpt-3.5\n"
            "      score: 80\n"
        )
        bm = self._reload_module()
        with patch("builtins.open", mock_open(read_data=yaml_content)), \
             patch("app.core.llm_model_benchmarks._yaml_path") as mock_path:
            mock_path.return_value = MagicMock()
            bm.invalidate_cache()
            result = bm.load_benchmarks()

        self.assertGreater(len(result), 0)
        # Each entry has model_id and score
        for entry in result:
            self.assertTrue(hasattr(entry, "model_id"))
            self.assertTrue(hasattr(entry, "score"))

    def test_uses_cache_on_subsequent_calls(self):
        bm = self._reload_module()
        # First call populates the cache
        with patch("builtins.open", mock_open(read_data="tiers:\n  tier1:\n    - {model_id: x, score: 1}\n")):
            bm.invalidate_cache()
            first = bm.load_benchmarks()

        # Second call must NOT re-open the file (cache hit)
        with patch("builtins.open") as mock_file:
            second = bm.load_benchmarks()
            mock_file.assert_not_called()
            self.assertEqual(first, second)

    def test_raises_llm_benchmark_file_error_on_missing_file(self):
        bm = self._reload_module()
        # Patch Path so the file doesn't exist
        with patch("app.core.llm_model_benchmarks._yaml_path") as mock_path:
            mock_path.return_value.exists.return_value = False
            bm.invalidate_cache()

            with self.assertRaises(bm.LLMBenchmarkFileError):
                bm.load_benchmarks()

    def test_invalidate_cache_clears_cache(self):
        bm = self._reload_module()
        with patch("builtins.open", mock_open(read_data="tiers:\n  tier1:\n    - {model_id: x, score: 1}\n")):
            bm.invalidate_cache()
            bm.load_benchmarks()
            bm.invalidate_cache()
            # After invalidate, next load must re-read the file
            with patch("builtins.open") as mock_file:
                bm.load_benchmarks()
                mock_file.assert_called()


# ---------------------------------------------------------------------------
# get_model_score
# ---------------------------------------------------------------------------

class TestGetModelScore(unittest.TestCase):
    def test_returns_score_when_model_in_tier(self):
        from app.core.llm_model_benchmarks import get_model_score
        entry = MagicMock(model_id="gpt-4", score=95)
        with patch("app.core.llm_model_benchmarks.load_benchmarks", return_value=[entry]):
            result = get_model_score("gpt-4")

        self.assertEqual(result, 95)

    def test_returns_none_when_model_not_in_benchmarks(self):
        from app.core.llm_model_benchmarks import get_model_score
        entry = MagicMock(model_id="gpt-4", score=95)
        with patch("app.core.llm_model_benchmarks.load_benchmarks", return_value=[entry]):
            result = get_model_score("nonexistent-model")

        self.assertIsNone(result)

    def test_returns_score_from_correct_entry(self):
        """If multiple entries exist, the matching one is returned."""
        from app.core.llm_model_benchmarks import get_model_score
        e1 = MagicMock(model_id="gpt-4", score=95)
        e2 = MagicMock(model_id="claude-opus", score=92)
        e3 = MagicMock(model_id="gpt-3.5", score=80)
        with patch("app.core.llm_model_benchmarks.load_benchmarks", return_value=[e1, e2, e3]):
            result = get_model_score("claude-opus")

        self.assertEqual(result, 92)

    def test_handles_empty_benchmarks_list(self):
        from app.core.llm_model_benchmarks import get_model_score
        with patch("app.core.llm_model_benchmarks.load_benchmarks", return_value=[]):
            result = get_model_score("any-model")

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------

class TestModuleStructure(unittest.TestCase):
    def test_llm_benchmark_file_error_is_exception(self):
        from app.core.llm_model_benchmarks import LLMBenchmarkFileError
        self.assertTrue(issubclass(LLMBenchmarkFileError, Exception))

    def test_benchmark_entry_class_exists(self):
        from app.core.llm_model_benchmarks import BenchmarkEntry
        self.assertTrue(BenchmarkEntry is not None)

    def test_invalidate_cache_is_callable(self):
        from app.core.llm_model_benchmarks import invalidate_cache
        self.assertTrue(callable(invalidate_cache))