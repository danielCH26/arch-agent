"""Tests HU8: definición de "la propuesta cita patrones" (lógica pura)."""

from __future__ import annotations

import copy

import pytest

from app.core.pattern_justification import (
    CITATION_TARGET_RATE,
    CURATED_SOURCE_LABEL,
    analyze_justification,
    source_for,
    summarize_citation_rate,
)

CITATIONS = [
    {"index": 1, "pattern_id": 7, "pattern_name": "Monolito modular", "source_role": "primary"},
    {"index": 2, "pattern_id": 3, "pattern_name": "Microservicios", "source_role": "tradeoff_option"},
]

PROPOSAL = """## Componentes
- API REST en FastAPI

## Tecnologias
- React, PostgreSQL, Jest

## Patrones
- Patrón principal: **Monolito modular** [1]

## Justificación del patrón principal
Encaja con un equipo de 3 personas y un MVP en 3 meses.
- Riesgo o costo: acoplamiento si los módulos no se respetan.

## Trade-offs y decisión
| Opción | Fuente RAG |
|---|---|
| Monolito modular | [1] |
"""


class TestAnalyzeJustification:
    def test_cites_when_primary_declared_in_sources_and_justified(self):
        result = analyze_justification(PROPOSAL, CITATIONS)

        assert result["cites_patterns"] is True
        assert result["declared_primary"] == "monolito modular"
        assert result["primary_pattern_id"] == 7
        assert result["primary_in_sources"] is True
        assert result["justified"] is True

    def test_technologies_without_citation_do_not_matter(self):
        # React / PostgreSQL / Jest no tienen patrón en el catálogo y no se exige citarlos.
        assert analyze_justification(PROPOSAL, CITATIONS)["cites_patterns"] is True

    def test_missing_primary_line_does_not_cite(self):
        markdown = PROPOSAL.replace("- Patrón principal: **Monolito modular** [1]", "- Monolito modular")
        result = analyze_justification(markdown, CITATIONS)
        assert result["declared_primary"] is None
        assert result["cites_patterns"] is False

    def test_declared_pattern_not_in_sources_does_not_cite(self):
        markdown = PROPOSAL.replace("**Monolito modular**", "Event Sourcing")
        result = analyze_justification(markdown, CITATIONS)
        assert result["declared_primary"] == "event sourcing"
        assert result["primary_in_sources"] is False
        assert result["cites_patterns"] is False

    def test_declaring_a_tradeoff_option_is_not_the_primary(self):
        markdown = PROPOSAL.replace("**Monolito modular**", "Microservicios")
        assert analyze_justification(markdown, CITATIONS)["cites_patterns"] is False

    def test_without_rag_sources_does_not_cite(self):
        assert analyze_justification(PROPOSAL, [])["cites_patterns"] is False
        assert analyze_justification(PROPOSAL, None)["primary_pattern_name"] is None

    def test_empty_justification_section_does_not_cite(self):
        start = PROPOSAL.index("## Justificación")
        end = PROPOSAL.index("## Trade-offs")
        markdown = PROPOSAL[:start] + "## Justificación del patrón principal\n\n" + PROPOSAL[end:]
        result = analyze_justification(markdown, CITATIONS)
        assert result["justified"] is False
        assert result["cites_patterns"] is False

    def test_missing_justification_section_does_not_cite(self):
        start = PROPOSAL.index("## Justificación")
        end = PROPOSAL.index("## Trade-offs")
        markdown = PROPOSAL[:start] + PROPOSAL[end:]
        assert analyze_justification(markdown, CITATIONS)["justified"] is False

    @pytest.mark.parametrize(
        "line",
        [
            "- Patrón principal: Monolito modular",
            "* **Patrón principal:** Monolito modular.",
            "1. PATRON PRINCIPAL: monolito modular [1][2]",
            "Patrón principal: Monolito Modular (Monolítica)",
            "- Patrón principal: `Monolito modular`",
        ],
    )
    def test_primary_line_variants(self, line):
        markdown = PROPOSAL.replace("- Patrón principal: **Monolito modular** [1]", line)
        assert analyze_justification(markdown, CITATIONS)["cites_patterns"] is True

    def test_numbered_justification_heading_is_recognized(self):
        markdown = PROPOSAL.replace(
            "## Justificación del patrón principal", "## 4. **Justificación**"
        )
        assert analyze_justification(markdown, CITATIONS)["justified"] is True

    def test_placeholder_justification_does_not_cite(self):
        start = PROPOSAL.index("## Justificación")
        end = PROPOSAL.index("## Trade-offs")
        markdown = PROPOSAL[:start] + "## Justificación del patrón principal\n- ...\n\n" + PROPOSAL[end:]
        assert analyze_justification(markdown, CITATIONS)["justified"] is False

    def test_primary_line_outside_patterns_section_is_ignored(self):
        markdown = PROPOSAL.replace("- Patrón principal: **Monolito modular** [1]", "- Monolito modular")
        markdown = markdown.replace(
            "Encaja con un equipo", "Patrón principal: Monolito modular\nEncaja con un equipo"
        )
        assert analyze_justification(markdown, CITATIONS)["declared_primary"] is None

    def test_primary_line_inside_code_block_is_ignored(self):
        markdown = PROPOSAL.replace(
            "- Patrón principal: **Monolito modular** [1]",
            "```\nPatrón principal: Monolito modular\n```",
        )
        assert analyze_justification(markdown, CITATIONS)["declared_primary"] is None

    def test_patterns_subheading_keeps_the_section(self):
        markdown = PROPOSAL.replace("## Patrones\n", "## Patrones\n### Principal\n")
        assert analyze_justification(markdown, CITATIONS)["cites_patterns"] is True

    def test_does_not_mutate_citations(self):
        citations = copy.deepcopy(CITATIONS)
        analyze_justification(PROPOSAL, citations)
        assert citations == CITATIONS

    def test_legacy_citations_without_source_role_do_not_cite(self):
        legacy = [{"pattern_id": 7, "pattern_name": "Monolito modular", "similarity": 0.9}]
        assert analyze_justification(PROPOSAL, legacy)["cites_patterns"] is False


def _cites_with(declared: str, primary_name: str) -> bool:
    markdown = PROPOSAL.replace("**Monolito modular**", declared)
    citations = [{"index": 1, "pattern_id": 1, "pattern_name": primary_name, "source_role": "primary"}]
    return analyze_justification(markdown, citations)["primary_in_sources"]


class TestPrimaryNameMatch:
    """El patrón declarado debe ser la fuente principal o un alias suyo, no un substring."""

    @pytest.mark.parametrize(
        ("declared", "primary_name"),
        [
            # Revisión HU8 v2: falsos positivos del substring en ambas direcciones.
            ("Arquitectura", "Arquitectura hexagonal (Puertos y Adaptadores)"),
            ("CQRS + Event Sourcing", "Event sourcing"),
            ("Microservicios", "Servicios"),
            ("Monolito modular", "Monolito"),
            ("Event", "Event sourcing"),
        ],
    )
    def test_partial_names_do_not_match(self, declared, primary_name):
        assert _cites_with(declared, primary_name) is False

    @pytest.mark.parametrize(
        ("declared", "primary_name"),
        [
            ("Monolito modular", "Monolito modular (Modular Monolith)"),
            ("Monolito modular (Monolítica)", "Monolito modular (Modular Monolith)"),
            ("Modular Monolith", "Monolito modular (Modular Monolith)"),
            ("Arquitectura hexagonal", "Arquitectura hexagonal (Puertos y Adaptadores)"),
            ("Hexagonal", "Arquitectura hexagonal (Puertos y Adaptadores)"),
            ("Puertos y adaptadores", "Arquitectura hexagonal (Puertos y Adaptadores)"),
            ("Arquitectura Hexagonal (Puertos y Adaptadores)", "Arquitectura hexagonal (Puertos y Adaptadores)"),
            ("Microservicio", "Microservicios"),
            ("Event Sourcing", "Event sourcing"),
        ],
    )
    def test_name_or_alias_matches(self, declared, primary_name):
        assert _cites_with(declared, primary_name) is True


class TestSummarizeCitationRate:
    def test_meets_target_at_eighty_percent(self):
        analyses = [{"cites_patterns": True}] * 4 + [{"cites_patterns": False}]
        summary = summarize_citation_rate(analyses)
        assert summary == {
            "proposals_total": 5,
            "proposals_citing": 4,
            "citation_rate": 0.8,
            "target": CITATION_TARGET_RATE,
            "meets_target": True,
        }

    def test_below_target(self):
        summary = summarize_citation_rate([{"cites_patterns": True}, {"cites_patterns": False}])
        assert summary["citation_rate"] == 0.5
        assert summary["meets_target"] is False

    def test_empty_is_zero_and_not_met(self):
        summary = summarize_citation_rate([])
        assert summary["proposals_total"] == 0
        assert summary["citation_rate"] == 0.0
        assert summary["meets_target"] is False


class TestCitationSource:
    def test_curated_catalog_by_default(self):
        assert source_for({"pattern_id": 1}) == {
            "type": "curated_catalog",
            "label": CURATED_SOURCE_LABEL,
            "filename": None,
        }

    def test_uploaded_document(self):
        source = source_for({"source_filename": "cockburn.pdf"})
        assert source["type"] == "source_upload"
        assert source["filename"] == "cockburn.pdf"


class TestSelectCitationsPayload:
    def test_citations_carry_index_and_source(self):
        from langchain_core.documents import Document

        from app.core.proposal_generator import _select_citations

        docs = [
            Document(
                page_content="resumen hexagonal",
                metadata={
                    "pattern_id": 7,
                    "pattern_name": "Hexagonal",
                    "category": "Estructural",
                    "chunk_type": "summary",
                    "similarity": 0.9,
                },
            ),
            Document(
                page_content="extracto subido",
                metadata={
                    "pattern_id": 3,
                    "pattern_name": "Capas",
                    "chunk_type": "source_upload",
                    "source_filename": "fowler.pdf",
                    "similarity": 0.8,
                },
            ),
        ]

        citations = _select_citations(docs, top_n=3)

        assert [c["index"] for c in citations] == [1, 2]
        assert citations[0]["source_role"] == "primary"
        assert "verify_url" not in citations[0]  # el front usa pattern_id
        assert citations[0]["source"]["type"] == "curated_catalog"
        assert citations[0]["category"] == "Estructural"
        assert citations[1]["source"]["filename"] == "fowler.pdf"
        assert citations[1]["chunk_type"] == "source_upload"
