"""Rúbrica determinista del resultado final (propuesta + ADR).

``scripts/eval_pattern_retrieval.py`` solo mide el retrieval (top-1/top-3), y
sus casos comparten vocabulario con los escenarios del catálogo, así que la
métrica sale inflada (ver docs/MEJORAS_RETRIEVAL_PATRONES.md). Esta rúbrica
mira lo que recibe el usuario: la tabla de trade-offs y el ADR.

Checks (cada uno pasa o no, con un detalle legible):

* ``respeta_restricciones``: con equipo chico y plazo corto, ni el patrón
  principal ni la recomendación son distribuidos; en un proyecto chico, 7.2
  no pasa de 6 tecnologías.
* ``cifras_con_origen``: la guía no trae cifras (SLA, dinero, capacidad,
  latencias) que no estén en los requerimientos o la propuesta, salvo las
  marcadas ``(supuesto)``.
* ``coherencia``: la recomendación de la tabla es el patrón principal, los
  componentes de 7.1 salen de la propuesta o del diagrama, y 7.2 no agrega
  tecnologías que la propuesta no nombra.
* ``alternativas_diversas``: las filas de la tabla son de al menos dos
  familias distintas cuando el catálogo las ofrecía.
* ``preocupaciones_dominio``: las preocupaciones del dominio esperadas se
  detectan y el ADR las trata (respuesta o pregunta abierta obligatoria).

La usan ``tests/eval/test_golden_rubric.py`` (CI, con salidas grabadas) y
``scripts/eval_adr_golden.py`` (contra un LLM real, cuando cambian los
prompts).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.core.adr_generator import (
    AdrContext,
    _requirements_text,
    _section_lines,
    _table_column,
    lint_adr_guide,
)
from app.core.domain_concerns import DOMAIN_CONCERNS, relevant_concerns
from app.core.text_norm import normalize_text

SMALL_PROJECT_MAX_TECHNOLOGIES = 6

_DISTRIBUTED_MARKERS = ("microserv", "orientada a eventos", "event-driven", "service mesh", "saga")


@dataclass
class RubricCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class RubricResult:
    checks: list[RubricCheck] = field(default_factory=list)

    @property
    def score(self) -> float:
        return sum(c.passed for c in self.checks) / len(self.checks) if self.checks else 0.0

    def by_name(self) -> dict[str, RubricCheck]:
        return {c.name: c for c in self.checks}


def _line_value(markdown: str, label: str) -> str:
    match = re.search(
        rf"^\s*[-*+]?\s*[*_]*{label}[*_]*\s*:\s*(.+)$", normalize_text(markdown), re.MULTILINE
    )
    return match.group(1).strip(" *_`.") if match else ""


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", normalize_text(text)) if w != "arquitectura"}


def _is_distributed(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in _DISTRIBUTED_MARKERS)


def _check_restrictions(
    proposal: str, guide: str, citations: list[dict], small: bool, tight: bool
) -> RubricCheck:
    problems = []
    primary = citations[0]["pattern_name"] if citations else ""
    recommendation = _line_value(proposal, "recomendacion")
    if tight and primary and _is_distributed(primary):
        problems.append(f"patrón principal distribuido con equipo chico y plazo corto: {primary}")
    if tight and recommendation and _is_distributed(recommendation):
        problems.append(f"recomienda una opción distribuida: {recommendation}")
    technologies = [c for c in _table_column(_section_lines(guide, "7.2"), "tecnolog") if c.strip(" -—")]
    if small and len(technologies) > SMALL_PROJECT_MAX_TECHNOLOGIES:
        problems.append(f"7.2 lista {len(technologies)} tecnologías (máximo {SMALL_PROJECT_MAX_TECHNOLOGIES})")
    return RubricCheck("respeta_restricciones", not problems, "; ".join(problems))


def _check_figures(ctx: AdrContext, guide: str) -> RubricCheck:
    figures = [w for w in lint_adr_guide(ctx, guide) if w.startswith("Cifras")]
    return RubricCheck("cifras_con_origen", not figures, "; ".join(figures))


def _check_coherence(ctx: AdrContext, guide: str) -> RubricCheck:
    problems = []
    primary = _line_value(ctx.proposal_markdown, "patron principal")
    recommendation = _line_value(ctx.proposal_markdown, "recomendacion")
    if primary and recommendation and not (
        _significant_words(primary) & _significant_words(recommendation)
    ):
        problems.append(f"la recomendación ({recommendation}) no es el patrón principal ({primary})")

    known = normalize_text(f"{ctx.proposal_markdown} {ctx.mermaid or ''}")
    components = [c for c in _table_column(_section_lines(guide, "7.1"), "componente") if c.strip(" -—")]
    unknown = [
        c for c in components
        if not any(word in known for word in _significant_words(c) or {normalize_text(c).strip()})
    ]
    if components and len(unknown) > len(components) * 0.3:
        problems.append("componentes de 7.1 que no están en la propuesta ni en el diagrama: " + ", ".join(unknown))

    new_tech = [w for w in lint_adr_guide(ctx, guide) if w.startswith("Tecnolog")]
    problems.extend(new_tech)
    return RubricCheck("coherencia", not problems, "; ".join(problems))


def _check_diversity(citations: list[dict], available_families: int) -> RubricCheck:
    families = {c.get("family") for c in citations if c.get("family")}
    needed = min(2, available_families)
    passed = len(families) >= needed
    return RubricCheck(
        "alternativas_diversas",
        passed,
        "" if passed else f"familias en la tabla: {sorted(families)} (el catálogo ofrecía {available_families})",
    )


def _check_concerns(ctx: AdrContext, markdown: str, expected: list[str]) -> RubricCheck:
    detected = {c.key for c in relevant_concerns(_requirements_text(ctx))}
    labels = {c.key: c for c in DOMAIN_CONCERNS}
    problems = []
    for key in expected:
        if key not in detected:
            problems.append(f"no se detectó la preocupación «{key}»")
            continue
        concern = labels[key]
        if normalize_text(concern.label) not in normalize_text(markdown):
            # Sin pregunta obligatoria: tiene que estar tratada en el texto.
            covered = re.compile(r"(?<![a-z0-9])(?:" + "|".join(concern.covered) + r")(?![a-z])")
            if not covered.search(normalize_text(markdown)):
                problems.append(f"el ADR no trata «{concern.label}»")
    return RubricCheck("preocupaciones_dominio", not problems, "; ".join(problems))


def evaluate(
    *,
    ctx: AdrContext,
    guide: Optional[str],
    markdown: str,
    citations: list[dict],
    small: bool,
    tight: bool,
    expected_concerns: list[str],
    available_families: int,
) -> RubricResult:
    """Aplica los cinco checks a una propuesta + ADR ya generados."""
    guide = guide or ""
    return RubricResult(
        checks=[
            _check_restrictions(ctx.proposal_markdown, guide, citations, small, tight),
            _check_figures(ctx, guide),
            _check_coherence(ctx, guide),
            _check_diversity(citations, available_families),
            _check_concerns(ctx, markdown, expected_concerns),
        ]
    )
