"""Cada patron curado declara su complejidad operativa (baja | media | alta)."""

from pathlib import Path

import yaml

PATTERNS_DIR = Path(__file__).resolve().parents[2] / "data" / "patterns"
VALID = {"baja", "media", "alta"}


def _patterns():
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(PATTERNS_DIR.glob("*.yaml"))
    ]


def test_every_pattern_declares_a_valid_complexity():
    for pattern in _patterns():
        assert pattern.get("complexity") in VALID, pattern["pattern_name"]


def test_there_is_at_least_one_low_complexity_pattern_per_category_of_small_projects():
    low = {p["pattern_name"] for p in _patterns() if p["complexity"] == "baja"}
    # Sin candidatos de complejidad baja el reordenamiento no tiene a donde ir.
    assert len(low) >= 2


def test_distributed_patterns_are_not_low_complexity():
    for pattern in _patterns():
        if pattern["category"].startswith("Distribuida"):
            assert pattern["complexity"] != "baja", pattern["pattern_name"]
