"""Rúbrica sobre los proyectos golden (data/golden/*.yaml).

Corre en CI con cada PR: si un cambio en los prompts, en la selección de
patrones o en el armado del ADR cambia el resultado de un caso, este test lo
muestra. Las salidas del LLM están grabadas en cada caso; para volver a
generarlas contra un modelo real usa ``scripts/eval_adr_golden.py --live``.
"""

from __future__ import annotations

import pytest

from app.core.golden_eval import evaluate_case, expected_checks, load_cases

CASES = load_cases()


def test_there_are_enough_varied_golden_cases():
    assert 8 <= len(CASES) <= 10
    assert len({case.kind for case in CASES}) >= 6
    assert len({case.id for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_rubric_matches_the_expected_result(case):
    result, _markdown, _citations = evaluate_case(case)
    checks = result.by_name()
    expected = expected_checks(case)
    assert set(expected) == set(checks), case.id
    mismatches = {
        name: (expected[name], checks[name].passed, checks[name].detail)
        for name in expected
        if checks[name].passed is not expected[name]
    }
    assert not mismatches, f"{case.id}: {mismatches}"


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_rendered_adr_never_carries_interface_prompts(case):
    _result, markdown, _citations = evaluate_case(case)
    assert "Punto de decisión" not in markdown
    assert "¿Aprueba" not in markdown


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_tradeoff_rows_have_a_primary_and_distinct_families(case):
    _result, _markdown, citations = evaluate_case(case)
    assert citations[0]["source_role"] == "primary"
    assert len({c.get("family") for c in citations}) >= 2


def test_pets_regression_flags_invented_figures_and_asks_about_maps():
    case = next(c for c in CASES if c.id == "mascotas-perdidas")
    result, markdown, _citations = evaluate_case(case)
    figures = result.by_name()["cifras_con_origen"].detail
    for figure in ("99", "2 vcpu", "4 gb", "$150"):
        assert figure in figures, figure
    assert "> **Revisión automática:**" in markdown
    assert "**Ubicación y mapas:**" in markdown
    assert "Gunicorn" in result.by_name()["coherencia"].detail
