"""Proyectos golden para evaluar la propuesta y el ADR de punta a punta.

Cada caso (``data/golden/*.yaml``) trae:

* el proyecto: descripción, perfil estructurado, resumen de la elicitación y
  sus preguntas y respuestas;
* ``candidates``: lo que devolvería el retrieval (patrón + similitud). Así la
  selección de filas (reglas duras, familias) corre sin base de datos ni
  embeddings;
* ``recorded``: una propuesta y una guía (sección 7) grabadas de una corrida
  real o escritas a mano para fijar un caso. En CI se evalúan esas salidas;
  ``scripts/eval_adr_golden.py --live`` las vuelve a generar con un LLM;
* ``expect``: el resultado esperado de cada check de la rúbrica y las
  preocupaciones del dominio que el sistema debe detectar.

El caso de la app de mascotas perdidas queda como regresión: su guía grabada
es la que salió con Gunicorn, Docker, "SLA 99 %" y "2 vCPU/4 GB".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from langchain_core.documents import Document

from app.core.adr_generator import AdrContext, render_adr_markdown
from app.core.adr_rubric import RubricResult, evaluate
from app.core.pattern_catalog import load_patterns, pattern_family
from app.core.project_context import format_requirements_summary
from app.core.proposal_generator import _profile_scale, _select_citations
from app.core.query_profile import normalize_profile

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "data" / "golden"
_FIXED_DATE = datetime(2026, 10, 17, tzinfo=timezone.utc)


@dataclass
class GoldenCase:
    id: str
    name: str
    kind: str
    description: str
    profile: dict
    resumen: dict
    preguntas_respuestas: list[dict]
    candidates: list[dict]
    proposal: str
    guide: Optional[str]
    mermaid: Optional[str]
    expect: dict = field(default_factory=dict)

    @property
    def requirements_text(self) -> str:
        return format_requirements_summary(self.resumen)


def load_cases(directory: Path | None = None) -> list[GoldenCase]:
    cases = []
    for path in sorted((directory or GOLDEN_DIR).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        recorded = data.get("recorded") or {}
        cases.append(
            GoldenCase(
                id=data["id"],
                name=data["name"],
                kind=data.get("kind", ""),
                description=data.get("description", ""),
                profile=normalize_profile(data.get("profile")) or {},
                resumen=data.get("resumen") or {},
                preguntas_respuestas=data.get("preguntas_respuestas") or [],
                candidates=data.get("candidates") or [],
                proposal=(recorded.get("proposal") or "").strip(),
                guide=(recorded.get("guide") or "").strip() or None,
                mermaid=(recorded.get("mermaid") or "").strip() or None,
                expect=data.get("expect") or {},
            )
        )
    return cases


def _complexity_by_name() -> dict[str, str]:
    return {p["pattern_name"]: p.get("complexity") for p in load_patterns()}


def candidate_documents(case: GoldenCase) -> list[Document]:
    complexity = _complexity_by_name()
    return [
        Document(
            page_content=item["name"],
            metadata={
                "pattern_id": index,
                "pattern_name": item["name"],
                "chunk_type": item.get("chunk_type", "summary"),
                "similarity": float(item["similarity"]),
                "complexity": complexity.get(item["name"]),
            },
        )
        for index, item in enumerate(case.candidates, start=1)
    ]


def select_rows(case: GoldenCase) -> list[dict]:
    """Filas de la tabla de trade-offs que elegiría el sistema para el caso."""
    return _select_citations(
        candidate_documents(case),
        min_similarity=0.0,
        explicit_text="\n".join(p for p in (case.name, case.description, case.requirements_text) if p),
        profile=case.profile or None,
    )


def build_context(case: GoldenCase, proposal: str, citations: list[dict]) -> AdrContext:
    return AdrContext(
        project_name=case.name,
        project_description=case.description,
        current_phase="revision",
        resumen=case.resumen,
        preguntas_respuestas=case.preguntas_respuestas,
        proposal_markdown=proposal,
        proposal_iteration=1,
        proposal_lifecycle="approved",
        citations=citations,
        mermaid=case.mermaid,
        diagram_approved=bool(case.mermaid),
    )


def available_families(case: GoldenCase) -> int:
    return len(
        {
            info["family"]
            for item in case.candidates
            for info in [pattern_family(item["name"])]
            if info
        }
    )


def evaluate_case(
    case: GoldenCase,
    *,
    proposal: Optional[str] = None,
    guide: Optional[str] = None,
    use_recorded: bool = True,
) -> tuple[RubricResult, str, list[dict]]:
    """Rúbrica del caso con la propuesta y la guía dadas (o las grabadas)."""
    citations = select_rows(case)
    proposal_text = proposal if proposal is not None else (case.proposal if use_recorded else "")
    guide_text = guide if guide is not None else (case.guide if use_recorded else None)
    ctx = build_context(case, proposal_text, citations)
    markdown = render_adr_markdown(ctx, llm_sections=guide_text, generated_at=_FIXED_DATE)
    small, tight = _profile_scale(case.profile or None)
    result = evaluate(
        ctx=ctx,
        guide=guide_text,
        markdown=markdown,
        citations=citations,
        small=small,
        tight=tight,
        expected_concerns=list(case.expect.get("concerns") or []),
        available_families=available_families(case),
    )
    return result, markdown, citations


def expected_checks(case: GoldenCase) -> dict[str, Any]:
    return dict(case.expect.get("checks") or {})
