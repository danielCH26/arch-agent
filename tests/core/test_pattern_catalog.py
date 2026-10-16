"""El catalogo curado debe ser rico en los campos que alimentan el retrieval."""

from pathlib import Path

import yaml

from app.core.pattern_catalog import CHUNK_TYPES, build_pattern_chunks, load_patterns

ROOT = Path(__file__).resolve().parents[2]
MAX_CHUNK_WORDS = 280  # ventana de multilingual-e5-small (ver test_pattern_knowledge_base)


def test_catalog_covers_enough_patterns_with_unique_names():
    patterns = load_patterns()
    names = [p["pattern_name"] for p in patterns]
    assert len(names) >= 15
    assert len(names) == len(set(names))


def test_every_pattern_builds_every_chunk_type_within_the_embedding_window():
    for pattern in load_patterns():
        chunks = build_pattern_chunks(pattern)
        assert set(chunks) == set(CHUNK_TYPES), pattern["pattern_name"]
        for kind, text in chunks.items():
            assert len(text.split()) <= MAX_CHUNK_WORDS, f"{pattern['pattern_name']}:{kind}"


def test_every_pattern_has_user_like_scenarios_and_fit_fields():
    for pattern in load_patterns():
        name = pattern["pattern_name"]
        scenarios = pattern.get("example_scenarios") or []
        assert len(scenarios) >= 2, name
        assert all(len(s.split()) >= 10 for s in scenarios), name
        assert len(pattern.get("quality_attributes") or []) >= 2, name
        assert (pattern.get("team_fit") or "").strip(), name


def test_build_pattern_chunks_omits_missing_optional_fields():
    minimal = {"pattern_name": "X", "description": "d", "use_cases": "u"}
    assert set(build_pattern_chunks(minimal)) == {"summary"}


def test_scenarios_chunk_names_the_pattern_and_keeps_every_scenario():
    chunks = build_pattern_chunks(
        {
            "pattern_name": "X",
            "description": "d",
            "use_cases": "u",
            "example_scenarios": ["uno", "dos"],
        }
    )
    assert chunks["scenarios"].startswith("X - ") and "uno" in chunks["scenarios"] and "dos" in chunks["scenarios"]


def test_eval_cases_only_reference_existing_patterns():
    names = {p["pattern_name"] for p in load_patterns()}
    cases = yaml.safe_load((ROOT / "data" / "eval" / "pattern_retrieval_cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 20
    for case in cases:
        assert {case["esperado"], *case.get("aceptables", [])} <= names, case["id"]
