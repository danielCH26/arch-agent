"""Tests HU8 -- justificación de propuestas basada en patrones del RAG.

Criterios de aceptación cubiertos:
- Cada decisión cita el patrón del RAG -> ``analyze_justification`` mide la
  cobertura por decisión y el prompt exige ``[n]`` en cada viñeta.
- Se muestra la fuente -> cada cita trae ``source`` + ``verify_url``.
- ≥80% de propuestas citan patrones -> ``summarize_citation_rate`` +
  ``meets_target``.
- El usuario puede verificar las fuentes -> ``verify_url`` apunta a
  ``GET /api/patterns/{id}`` (ver tests/api/test_patterns_detail.py).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.documents import Document

from app.core.pattern_justification import (
    CITATION_TARGET_RATE,
    CURATED_SOURCE_LABEL,
    analyze_justification,
    build_citations,
    extract_decisions,
    summarize_citation_rate,
)


def _doc(pattern_id, name, similarity, text="texto", **extra):
    metadata = {
        "pattern_id": pattern_id,
        "pattern_name": name,
        "similarity": similarity,
        "category": "Distribuida",
        "chunk_type": "summary",
        **extra,
    }
    return Document(page_content=text, metadata=metadata)


CITED_PROPOSAL = """Contexto general del proyecto.

## Componentes
- **API Gateway**: punto de entrada único para web y móvil [1]
- **Servicio de pedidos**: dominio aislado con puertos y adaptadores [2]

## Tecnologías
- **PostgreSQL**: consistencia transaccional (sin patron del catalogo)

## Patrones
- **Hexagonal**: desacopla el dominio de la infraestructura [2]
- **BFF**: respuestas adaptadas por cliente [1, 2]
"""


class TestBuildCitations:
    def test_numbers_citations_from_one_ordered_by_similarity(self):
        citations = build_citations(
            [_doc(1, "BFF", 0.87), _doc(2, "Hexagonal", 0.93)],
            min_similarity=0.85,
        )
        assert [c["index"] for c in citations] == [1, 2]
        assert [c["pattern_name"] for c in citations] == ["Hexagonal", "BFF"]

    def test_deduplicates_chunks_of_the_same_pattern_keeping_best(self):
        citations = build_citations(
            [
                _doc(1, "BFF", 0.86, text="tradeoffs"),
                _doc(1, "BFF", 0.95, text="summary"),
                _doc(2, "CQRS", 0.90),
            ],
            min_similarity=0.85,
        )
        assert len(citations) == 2
        assert citations[0]["pattern_id"] == 1
        assert citations[0]["similarity"] == 0.95
        assert citations[0]["snippet"] == "summary"

    def test_drops_below_threshold_and_caps_max_patterns(self):
        docs = [_doc(i, f"P{i}", 0.99 - i * 0.01) for i in range(10)]
        docs.append(_doc(99, "Bajo", 0.5))
        citations = build_citations(docs, min_similarity=0.85, max_patterns=5)
        assert len(citations) == 5
        assert all(c["pattern_id"] != 99 for c in citations)

    def test_exposes_source_and_verify_url(self):
        curated, uploaded = build_citations(
            [
                _doc(1, "BFF", 0.95),
                _doc(2, "CQRS", 0.90, source_filename="fowler_cqrs.pdf"),
            ],
            min_similarity=0.85,
        )
        assert curated["source"]["type"] == "curated_catalog"
        assert curated["source"]["label"] == CURATED_SOURCE_LABEL
        assert curated["verify_url"] == "/api/patterns/1"
        assert uploaded["source"]["type"] == "source_upload"
        assert "fowler_cqrs.pdf" in uploaded["source"]["label"]
        assert uploaded["cited"] is False

    def test_snippet_capped_to_240_chars(self):
        (citation,) = build_citations(
            [_doc(1, "BFF", 0.95, text="x" * 1000)], min_similarity=0.85
        )
        assert len(citation["snippet"]) == 240


class TestExtractDecisions:
    def test_only_bullets_inside_decision_sections(self):
        decisions = extract_decisions(CITED_PROPOSAL)
        assert [d["section"] for d in decisions] == [
            "componentes",
            "componentes",
            "tecnologias",  # accent in heading is normalized
            "patrones",
            "patrones",
        ]

    def test_ignores_template_placeholders_and_other_sections(self):
        markdown = "## Riesgos\n- algo [1]\n## Patrones\n- ...\n"
        assert extract_decisions(markdown) == []


class TestAnalyzeJustification:
    def _citations(self):
        return build_citations(
            [_doc(7, "BFF", 0.95), _doc(8, "Hexagonal", 0.9), _doc(9, "CQRS", 0.88)],
            min_similarity=0.85,
        )

    def test_measures_coverage_per_decision(self):
        result = analyze_justification(CITED_PROPOSAL, self._citations())
        assert result["decisions_total"] == 5
        assert result["decisions_cited"] == 4
        assert result["coverage"] == 0.8
        assert result["cites_patterns"] is True
        assert result["cited_indices"] == [1, 2]
        assert result["uncited_decisions"][0]["section"] == "tecnologias"

    def test_marks_cited_flag_on_referenced_sources_only(self):
        citations = self._citations()
        analyze_justification(CITED_PROPOSAL, citations)
        assert [c["cited"] for c in citations] == [True, True, False]

    def test_hallucinated_reference_does_not_count(self):
        markdown = "## Patrones\n- **Saga**: transacciones [9]\n"
        result = analyze_justification(markdown, self._citations())
        assert result["decisions_cited"] == 0
        assert result["cites_patterns"] is False
        assert result["invalid_refs"] == [9]

    def test_no_citations_means_no_pattern_cited(self):
        result = analyze_justification(CITED_PROPOSAL, [])
        assert result["cites_patterns"] is False
        assert result["coverage"] == 0.0

    def test_legacy_citations_without_index_use_position(self):
        # Filas persistidas antes de HU8: sin ``index``, numeradas por posición.
        legacy = [
            {"pattern_id": 7, "pattern_name": "BFF", "similarity": 0.9},
            {"pattern_id": 8, "pattern_name": "Hexagonal", "similarity": 0.9},
        ]
        result = analyze_justification("## Patrones\n- **X**: y [2]\n", legacy)
        assert result["cited_indices"] == [2]
        assert legacy[1]["cited"] is True


class TestCitationRateKR:
    def test_meets_target_at_eighty_percent(self):
        analyses = [{"cites_patterns": True, "decisions_total": 2, "decisions_cited": 2}] * 4
        analyses.append({"cites_patterns": False, "decisions_total": 2, "decisions_cited": 0})
        summary = summarize_citation_rate(analyses)
        assert summary["citation_rate"] == 0.8
        assert summary["target_rate"] == CITATION_TARGET_RATE == 0.8
        assert summary["meets_target"] is True
        assert summary["decision_coverage"] == 0.8

    def test_below_target(self):
        analyses = [{"cites_patterns": True}, {"cites_patterns": False}]
        assert summarize_citation_rate(analyses)["meets_target"] is False

    def test_empty_never_meets_target(self):
        summary = summarize_citation_rate([])
        assert summary["proposals_total"] == 0
        assert summary["meets_target"] is False


class TestPromptRequiresCitations:
    def test_prompt_lists_numbered_sources_and_citation_rules(self):
        from app.core.proposal_generator import _build_prompt

        citations = build_citations(
            [_doc(7, "BFF", 0.95, text="punto de entrada")], min_similarity=0.85
        )
        prompt = _build_prompt(
            citations=citations, prior_content=None, feedback=None, project_name="Demo"
        )
        assert "[1] BFF (Distribuida)" in prompt
        assert "Reglas de justificacion" in prompt
        assert "nunca inventes fuentes" in prompt.replace("\n", " ").replace("  ", " ")

    def test_prompt_without_sources_forbids_references(self):
        from app.core.proposal_generator import _build_prompt

        prompt = _build_prompt(
            citations=[], prior_content=None, feedback=None, project_name="Demo"
        )
        assert "NO uses referencias" in prompt
        assert "No se recuperaron patrones relevantes." in prompt


class TestGenerateStreamDonePayload:
    """El evento ``done`` trae las citas marcadas y el análisis de justificación."""

    def test_done_includes_justification_and_cited_flags(self):
        from app.core import proposal_generator as gen

        class FakeModel:
            async def astream(self, prompt):
                for piece in CITED_PROPOSAL.splitlines(keepends=True):
                    yield SimpleNamespace(content=piece)

        project = SimpleNamespace(name="Demo", description="tienda online")
        docs = [_doc(7, "BFF", 0.95), _doc(8, "Hexagonal", 0.9), _doc(9, "CQRS", 0.88)]
        persisted = {}

        def fake_persist(**kwargs):
            persisted.update(kwargs)
            return 11, 22

        async def fake_mirror(**kwargs):
            return None

        async def collect():
            generator = gen.ProposalGenerator(user_id=1, project_id=5)
            return [event async for event in generator.generate_stream()]

        with patch.object(gen, "_load_project_and_session", return_value=(project, 3)), \
             patch.object(gen, "_retrieve_patterns", return_value=docs), \
             patch.object(gen, "build_langchain_model", return_value=FakeModel()), \
             patch.object(gen, "_persist_proposal_and_log", side_effect=fake_persist), \
             patch.object(gen, "_engram_mirror", side_effect=fake_mirror):
            events = asyncio.run(collect())

        names = [name for name, _ in events]
        assert names[0] == "sources"
        assert names[-1] == "done"
        done = events[-1][1]
        assert done["proposal_id"] == 11
        assert done["justification"]["decisions_cited"] == 4
        assert [c["cited"] for c in done["citations"]] == [True, True, False]
        # Lo persistido en JSONB lleva el mismo flag ``cited``.
        assert [c["cited"] for c in persisted["citations"]] == [True, True, False]


@pytest.mark.parametrize(
    "markdown,expected",
    [
        ("## Patrones\n- **A**: b [1]\n", True),
        ("## Patrones\n- **A**: b (sin patron del catalogo)\n", False),
        ("## Patrones\n* **A**: b [1,2]\n", True),
        ("## Patrones\n1. **A**: b [2]\n", True),
    ],
)
def test_bullet_styles_are_recognized(markdown, expected):
    citations = build_citations(
        [_doc(1, "A", 0.95), _doc(2, "B", 0.9)], min_similarity=0.85
    )
    assert analyze_justification(markdown, citations)["cites_patterns"] is expected
