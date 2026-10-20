import pytest

from app.core.proposal_generator import ProposalGenerator


def test_generate_sync_returns_proposal_skeleton():
    result = ProposalGenerator().generate_sync(42)
    assert result["project_id"] == 42
    assert set(result["content"]) == {"componentes", "tecnologias", "patrones"}
    assert result["citations"] == []
    assert result["lifecycle"] == "proposed"


def test_build_prompt_includes_full_prior_proposal_and_feedback_last():
    from app.core.proposal_generator import _build_prompt

    # El tema a cambiar esta DESPUES del caracter 1500, donde antes se cortaba.
    prior = ("x" * 3000) + " Observabilidad: Prometheus, Grafana, Loki, OpenTelemetry"
    feedback = "en la observabilidad solo quiero Grafana Loki y OpenTelemetry"

    prompt = _build_prompt(
        citations=[],
        prior_content=prior,
        feedback=feedback,
        project_name="Flota",
    )

    assert "Prometheus" in prompt  # la propuesta previa llega completa
    assert "CAMBIOS SOLICITADOS POR EL USUARIO" in prompt
    assert feedback in prompt
    # el feedback va despues de la propuesta previa (recencia) y hay recordatorio final
    assert prompt.index("Propuesta previa") < prompt.index("CAMBIOS SOLICITADOS")
    assert "Recordatorio final" in prompt


def test_build_prompt_without_feedback_has_no_change_block():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
    assert "CAMBIOS SOLICITADOS" not in prompt
    assert "Recordatorio final" not in prompt


def test_retrieve_patterns_asks_for_many_chunks_so_top_n_can_dedupe():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    with patch.object(gen, "similarity_search", return_value=([], {})) as mocked:
        gen._retrieve_patterns("consulta", user_id=1)

    kwargs = mocked.call_args.kwargs
    assert kwargs["scope"] == "patterns"
    assert kwargs["k"] == gen.PROPOSAL_RAG_CANDIDATE_CHUNKS
    assert kwargs["k"] > gen.PROPOSAL_RAG_TOP_N


def test_build_prompt_without_citations_does_not_ask_for_bracket_numbers():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
    assert "cita el numero entre corchetes" not in prompt
    assert "números entre corchetes" in prompt


def test_build_prompt_marks_one_primary_pattern_and_secondary_references():
    from app.core.proposal_generator import _build_prompt, _select_citations
    from langchain_core.documents import Document

    citations = _select_citations([
        Document(page_content="separa lectura y escritura", metadata={"pattern_id": 1, "pattern_name": "CQRS", "similarity": 0.9}),
        Document(page_content="coordina servicios", metadata={"pattern_id": 2, "pattern_name": "Saga", "similarity": 0.8}),
    ])
    prompt = _build_prompt(
        citations=citations, prior_content=None, feedback=None, project_name="P"
    )
    assert "[1] CQRS" in prompt
    assert citations[0]["source_role"] == "primary"
    assert citations[1]["source_role"] == "tradeoff_option"
    assert "Patrón principal: <nombre>" in prompt
    # F10: los patrones secundarios ya no van en una linea aparte; cada [n]
    # recuperado es una fila de la tabla de trade-offs.
    assert "[2] Saga" in prompt
    assert "una fila por cada patrón [n] recuperado" in prompt
    assert "cita el numero entre corchetes" not in prompt


def test_microservices_prompt_includes_distributed_architecture_baseline():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "Microservicios", "source_role": "primary"}],
        prior_content=None,
        feedback=None,
        project_name="Pedidos",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" in prompt
    assert "API Gateway" in prompt
    assert "base de datos privada por servicio" in prompt


def test_build_prompt_requires_comparison_then_a_single_recommendation():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
    assert "REGLA DE DECISION" in prompt
    assert "compara alternativas" in prompt
    assert "UNA sola opción" in prompt
    # La regla va antes del formato de salida para que el modelo la vea primero.
    assert prompt.index("REGLA DE DECISION") < prompt.index("Formato OBLIGATORIO")


def test_build_prompt_requires_a_concrete_primary_pattern_justification():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "Microservicios", "source_role": "primary"}],
        prior_content=None,
        feedback=None,
        project_name="Pedidos",
    )

    assert "## Justificación del patrón principal" in prompt
    assert "Motivo de elección" in prompt
    assert "Reflejo en la arquitectura" in prompt
    assert "Beneficio esperado" in prompt
    assert "Riesgo o costo" in prompt


def test_build_prompt_makes_budget_team_and_timeline_design_constraints():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[],
        prior_content=None,
        feedback=None,
        project_name="Inventario",
        requirements_text="Restricciones:\n- Presupuesto: 20 millones COP\n- Equipo de 3\n- MVP en 12 semanas",
    )

    assert "RESTRICCIONES DE VIABILIDAD" in prompt
    assert "presupuesto, el tamaño y capacidad del equipo, y el plazo" in prompt
    assert "no inventes cifras" in prompt


def test_secondary_microservices_pattern_does_not_force_distributed_baseline():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[
            {"pattern_name": "Arquitectura en capas (Layered)", "source_role": "primary"},
            {"pattern_name": "Microservicios", "source_role": "tradeoff_option"},
        ],
        prior_content=None,
        feedback=None,
        project_name="Agenda de citas",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: arquitectura en capas" in prompt
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt


def test_prior_proposal_secondary_references_do_not_force_baseline():
    from app.core.proposal_generator import _build_prompt

    prior = (
        "## Patrones\n"
        "- Patrón principal: Arquitectura en capas (Layered)\n"
        "- Consultados no citados: Microservicios, CQRS\n"
    )
    prompt = _build_prompt(
        citations=[], prior_content=prior, feedback="cambia la base de datos a SQLite",
        project_name="Agenda de citas",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: arquitectura en capas" in prompt
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt


def test_explicit_user_feedback_can_still_ask_for_microservices():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[], prior_content=None, feedback="quiero microservicios",
        project_name="Pedidos",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" in prompt


def test_microservices_baseline_is_subordinate_to_viability_and_has_minimal_version():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "Microservicios", "source_role": "primary"}],
        prior_content=None,
        feedback=None,
        project_name="Pedidos",
        requirements_text="Restricciones:\n- Presupuesto: bajo\n- Equipo de 2",
    )

    assert "version MINIMA" in prompt
    assert "sin broker de eventos" in prompt
    # La viabilidad se lee ANTES que la estructura base y manda sobre ella.
    assert prompt.index("RESTRICCIONES DE VIABILIDAD") < prompt.index("ESTRUCTURA BASE SELECCIONADA")
    assert "tienen prioridad sobre la ESTRUCTURA BASE" in prompt


def test_build_prompt_enforces_proportionality_against_over_engineering():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")

    assert "PROPORCIONALIDAD" in prompt
    assert "Kubernetes" in prompt
    assert "SOLO se incluye si un requisito explícito la exige" in prompt
    assert "Asume presupuesto y equipo pequeños" in prompt
    assert "opcion mas simple y barata" in prompt
    assert "qué se dejó fuera a propósito" in prompt


def _chunk(name, pid, chunk_type, similarity):
    from langchain_core.documents import Document

    return Document(
        page_content=f"{name} [{chunk_type}]",
        metadata={
            "pattern_id": pid,
            "pattern_name": name,
            "chunk_type": chunk_type,
            "similarity": similarity,
        },
    )


def test_when_not_to_use_chunk_does_not_make_a_pattern_the_primary():
    """Proyecto chico: el chunk 'no usar' de Microservicios es el mas parecido a
    la consulta ("equipo pequeno, presupuesto limitado"), pero no debe ganar."""
    from app.core.proposal_generator import _select_citations

    docs = [
        _chunk("Microservicios", 1, "when_not_to_use", 0.91),
        _chunk("Microservicios", 1, "summary", 0.80),
        _chunk("Arquitectura en capas (Layered)", 2, "summary", 0.86),
        _chunk("Monolito modular (Modular Monolith)", 3, "summary", 0.84),
    ]

    citations = _select_citations(docs, top_n=3, min_similarity=0.0)

    assert citations[0]["pattern_name"] == "Arquitectura en capas (Layered)"
    assert citations[0]["source_role"] == "primary"
    # el patron descartado queda al final y su snippet nunca es el chunk 'no usar'
    assert citations[-1]["pattern_name"] == "Microservicios"
    assert "when_not_to_use" not in citations[-1]["snippet"]


def test_pattern_still_wins_when_its_fit_chunk_is_the_best_match():
    from app.core.proposal_generator import _select_citations

    docs = [
        _chunk("Microservicios", 1, "summary", 0.90),
        _chunk("Microservicios", 1, "when_not_to_use", 0.70),
        _chunk("Arquitectura en capas (Layered)", 2, "summary", 0.82),
    ]

    citations = _select_citations(docs, top_n=3, min_similarity=0.0)

    assert citations[0]["pattern_name"] == "Microservicios"


def test_select_citations_falls_back_when_only_avoid_chunks_are_found():
    from app.core.proposal_generator import _select_citations

    docs = [
        _chunk("Microservicios", 1, "when_not_to_use", 0.9),
        _chunk("CQRS", 2, "when_not_to_use", 0.8),
    ]

    citations = _select_citations(docs, top_n=3, min_similarity=0.0)

    assert [c["pattern_name"] for c in citations] == ["Microservicios", "CQRS"]


def _pat(name, pid, similarity, complexity=None, chunk_type="summary"):
    from langchain_core.documents import Document

    return Document(
        page_content=f"{name} [{chunk_type}]",
        metadata={
            "pattern_id": pid,
            "pattern_name": name,
            "chunk_type": chunk_type,
            "similarity": similarity,
            "complexity": complexity,
        },
    )


def test_citations_preserve_curated_sources_for_the_ui():
    from app.core.proposal_generator import _select_citations

    source = {
        "titulo": "Hexagonal architecture (Alistair Cockburn)",
        "url": "https://alistair.cockburn.us/hexagonal-architecture/",
    }
    doc = _pat("Arquitectura hexagonal", 7, 0.91)
    doc.metadata["fuentes"] = [source]

    citations = _select_citations([doc], top_n=1, min_similarity=0.0)

    assert citations[0]["fuentes"] == [source]


def test_complexity_penalty_prefers_simple_pattern_on_close_similarity():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("Microservicios", 1, 0.88, "alta"),
        _pat("API Gateway + Backend for Frontend (BFF)", 2, 0.86, "media"),
        _pat("Monolito modular (Modular Monolith)", 3, 0.84, "baja"),
    ]
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.03):
        citations = gen._select_citations(docs, top_n=3, min_similarity=0.0)

    assert [c["pattern_name"] for c in citations] == [
        "Monolito modular (Modular Monolith)",
        "API Gateway + Backend for Frontend (BFF)",
        "Microservicios",
    ]
    # la similitud que se reporta sigue siendo la real, no la ajustada
    assert citations[0]["similarity"] == 0.84


def test_complexity_penalty_is_soft_a_much_better_match_still_wins():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("Microservicios", 1, 0.95, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.80, "baja"),
    ]
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.03):
        citations = gen._select_citations(docs, top_n=2, min_similarity=0.0)

    assert citations[0]["pattern_name"] == "Microservicios"


def test_complexity_penalty_is_waived_when_user_names_the_pattern():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("Microservicios", 1, 0.84, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.86, "baja"),
    ]
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.03):
        without = gen._select_citations(docs, top_n=2, min_similarity=0.0)
        named = gen._select_citations(
            docs, top_n=2, min_similarity=0.0,
            explicit_text="Necesitamos Microservicios por dominio",
        )

    assert without[0]["pattern_name"] == "Arquitectura en capas (Layered)"
    # sin penalizacion Microservicios (0.84) sigue detras de Layered (0.86):
    # nombrarlo solo evita el castigo, no lo fuerza como principal
    assert named[0]["pattern_name"] == "Arquitectura en capas (Layered)"

    docs[0].metadata["similarity"] = 0.865
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.03):
        assert gen._select_citations(docs, top_n=2, min_similarity=0.0)[0][
            "pattern_name"
        ] == "Arquitectura en capas (Layered)"
        assert gen._select_citations(
            docs, top_n=2, min_similarity=0.0,
            explicit_text="quiero microservicio",
        )[0]["pattern_name"] == "Microservicios"


def test_pattern_aliases_match_short_and_translated_names():
    from app.core.proposal_generator import _explicitly_requested

    assert _explicitly_requested("Arquitectura hexagonal (Puertos y Adaptadores)", "Usar hexagonal")
    assert _explicitly_requested("API Gateway + Backend for Frontend (BFF)", "necesito un BFF")
    assert _explicitly_requested("Microservicios", "una arquitectura de microservicio")
    assert _explicitly_requested("Event sourcing", "con Event Sourcing")
    assert not _explicitly_requested("Microservicios", "un monolito sencillo")
    assert not _explicitly_requested("Microservicios", None)


def test_penalty_zero_disables_complexity_adjustment():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("Microservicios", 1, 0.88, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.86, "baja"),
    ]
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.0):
        citations = gen._select_citations(docs, top_n=2, min_similarity=0.0)

    assert citations[0]["pattern_name"] == "Microservicios"


def test_prompt_requires_coherence_and_blocks_redundant_layers():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")

    assert "COHERENCIA (obligatoria)" in prompt
    assert "Repository/DAO sobre un ORM" in prompt
    assert "planificador del framework o un cron" in prompt
    assert "No inventes métricas" in prompt
    assert "REST/GraphQL" in prompt
    assert "no más de 6" in prompt
    # la coherencia se lee antes de la regla de decision y del formato
    assert prompt.index("COHERENCIA") < prompt.index("REGLA DE DECISION") < prompt.index("Formato OBLIGATORIO")


# --- El feedback del usuario manda sobre el ranking del RAG ----------------


def test_feedback_naming_a_pattern_makes_it_primary_even_if_rag_prefers_another():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("CQRS (Command Query Responsibility Segregation)", 1, 0.90, "alta"),
        _pat("Arquitectura hexagonal (Puertos y Adaptadores)", 2, 0.80, "media"),
        _pat("Arquitectura en capas (Layered)", 3, 0.85, "baja"),
    ]

    citations = _select_citations(
        docs, top_n=3, min_similarity=0.0, feedback="cambia la arquitectura a hexagonal"
    )

    assert citations[0]["pattern_name"] == "Arquitectura hexagonal (Puertos y Adaptadores)"
    assert citations[0]["source_role"] == "primary"


def test_feedback_rejecting_a_pattern_removes_it_from_the_citations():
    from app.core.proposal_generator import _select_citations

    cqrs = "CQRS (Command Query Responsibility Segregation)"
    docs = [
        _pat(cqrs, 1, 0.95, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.80, "baja"),
        _pat("Monolito modular (Modular Monolith)", 3, 0.78, "baja"),
    ]

    for feedback in (
        "no quiero CQRS",
        "sin CQRS, algo mas simple",
        "quita CQRS",
        "usa capas en vez de CQRS",
    ):
        citations = _select_citations(
            docs, top_n=3, min_similarity=0.0, feedback=feedback
        )
        assert cqrs not in [c["pattern_name"] for c in citations], feedback


def test_feedback_change_from_old_to_new_pattern_keeps_only_the_new_one():
    from app.core.proposal_generator import _select_citations

    cqrs = "CQRS (Command Query Responsibility Segregation)"
    hexagonal = "Arquitectura hexagonal (Puertos y Adaptadores)"
    docs = [
        _pat(cqrs, 1, 0.95, "alta"),
        _pat(hexagonal, 2, 0.80, "media"),
        _pat("Arquitectura en capas (Layered)", 3, 0.85, "baja"),
    ]

    for feedback in (
        "cambia CQRS por hexagonal",
        "cambia la arquitectura de CQRS a hexagonal",
        "quiero hexagonal en vez de CQRS",
        "no quiero CQRS, mejor hexagonal",
    ):
        citations = _select_citations(
            docs, top_n=3, min_similarity=0.0, feedback=feedback
        )
        names = [c["pattern_name"] for c in citations]
        assert names[0] == hexagonal, feedback
        assert cqrs not in names, feedback


def test_feedback_without_pattern_names_does_not_change_the_ranking():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("Arquitectura en capas (Layered)", 1, 0.86, "baja"),
        _pat("Microservicios", 2, 0.90, "alta"),
    ]
    with_feedback = _select_citations(
        docs, top_n=2, min_similarity=0.0, feedback="agrega cache con Redis"
    )
    without = _select_citations(docs, top_n=2, min_similarity=0.0)

    assert [c["pattern_name"] for c in with_feedback] == [
        c["pattern_name"] for c in without
    ]


def test_requirements_naming_a_pattern_do_not_force_it_only_feedback_does():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("Arquitectura en capas (Layered)", 1, 0.86, "baja"),
        _pat("Microservicios", 2, 0.80, "alta"),
    ]

    citations = _select_citations(
        docs, top_n=2, min_similarity=0.0, explicit_text="queremos microservicios"
    )

    assert citations[0]["pattern_name"] == "Arquitectura en capas (Layered)"


def test_default_complexity_penalty_demotes_cqrs_on_a_close_call():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("CQRS (Command Query Responsibility Segregation)", 1, 0.90, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.83, "baja"),
    ]
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.08):
        citations = gen._select_citations(docs, top_n=2, min_similarity=0.0)

    assert citations[0]["pattern_name"] == "Arquitectura en capas (Layered)"


def test_baseline_ignores_prior_proposal_style_when_user_asks_to_change_it():
    from app.core.proposal_generator import _build_prompt

    prior = (
        "## Componentes\n- API Gateway\n- Servicio de pedidos\n"
        "## Patrones\n- Patrón principal: Microservicios\n"
    )
    prompt = _build_prompt(
        citations=[{"pattern_name": "Arquitectura en capas (Layered)", "source_role": "primary"}],
        prior_content=prior,
        feedback="cambia microservicios por arquitectura en capas",
        project_name="Agenda",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: arquitectura en capas" in prompt
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt


def test_negated_style_in_feedback_does_not_trigger_its_baseline():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "Arquitectura en capas (Layered)", "source_role": "primary"}],
        prior_content=None,
        feedback="no quiero microservicios",
        project_name="Agenda",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: arquitectura en capas" in prompt
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt


def test_feedback_prompt_lets_the_user_change_the_primary_pattern():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "CQRS", "source_role": "primary"}],
        prior_content="## Patrones\n- Patrón principal: CQRS\n",
        feedback="cambia a arquitectura en capas",
        project_name="Biblioteca",
    )

    assert "salvo que los CAMBIOS SOLICITADOS pidan otro patron" in prompt
    assert "ELIMINA los componentes que solo existian por el anterior" in prompt

    without_feedback = _build_prompt(
        citations=[{"pattern_name": "CQRS", "source_role": "primary"}],
        prior_content=None,
        feedback=None,
        project_name="Biblioteca",
    )
    assert "salvo que los CAMBIOS SOLICITADOS" not in without_feedback


def test_prompt_caps_technologies_and_blocks_heavy_primary_patterns():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")

    assert "Tecnologías: como máximo 6" in prompt
    assert "CI/CD, backups" in prompt
    assert "no son el patrón principal de un proyecto sencillo" in prompt


def test_prompt_requires_technology_justification_and_motivating_requirement():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")

    assert "| Tecnología | Justificación | Requisito que lo motiva |" in prompt
    assert "no una ventaja genérica" in prompt


def test_tight_mvp_prohibits_distributed_patterns_as_the_primary_choice():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("Microservicios", 1, 0.98, "alta"),
        _pat("Monolito modular (Modular Monolith)", 2, 0.80, "baja"),
        _pat("Arquitectura hexagonal (Puertos y Adaptadores)", 3, 0.79, "media"),
    ]

    citations = _select_citations(
        docs,
        top_n=3,
        min_similarity=0.0,
        explicit_text="MVP en 3 meses con equipo de 4 desarrolladores; queremos microservicios",
    )

    assert citations[0]["pattern_name"] == "Monolito modular (Modular Monolith)"
    assert citations[-1]["pattern_name"] == "Microservicios"


def test_prompt_requires_concrete_operational_tradeoffs_and_tight_mvp_guardrail():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[],
        prior_content=None,
        feedback=None,
        project_name="MVP",
        requirements_text="MVP en 3 meses con equipo de 4 desarrolladores",
    )

    assert "REGLAS DE TRADE-OFFS REALES" in prompt
    assert "queda PROHIBIDO recomendar microservicios" in prompt
    assert "debugging local" in prompt
    assert "curva de aprendizaje DevOps" in prompt
    assert "riesgo de consistencia" in prompt
    assert "sobrecarga de mantenimiento" in prompt
    assert "seguridad y disponibilidad base" in prompt


# --- Propuestas cortadas a la mitad no se guardan --------------------------

_FULL_PROPOSAL = """## Componentes
- API Layer - FastAPI
- Persistence Layer - PostgreSQL

## Tecnologias
- Lenguaje: Python

## Patrones
- Patrón principal: Arquitectura en capas (Layered)

## Justificación del patrón principal
- Motivo de elección: ...
- Reflejo en la arquitectura: ...
- Beneficio esperado: ...
- Riesgo o costo: ...

## Trade-offs y decisión
| Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG |
| --- | --- | --- | --- | --- | --- |
| Capas | Simple | Escala conjunta | Baja | Alto | [1] |
| Modular | Límites claros | Requiere disciplina | Media | Alto | [2] |
| Microservicios | Escala independiente | Operación compleja | Alta | Bajo | [3] |
- Recomendación: Capas
- Punto de decisión: ¿Aprueba los trade-offs?
"""


def test_missing_sections_accepts_a_complete_proposal():
    from app.core.proposal_generator import _missing_sections

    assert _missing_sections(_FULL_PROPOSAL) == []


def test_missing_sections_detects_a_proposal_cut_after_components():
    from app.core.proposal_generator import _missing_sections

    cut = "## Componentes\n- API Layer - FastAPI\n- Persistence Layer - "

    assert _missing_sections(cut) == [
        "Tecnologias",
        "Patrones",
        "Justificación del patrón principal",
        "Trade-offs y decisión",
    ]


def test_missing_sections_detects_a_cut_inside_the_justification():
    from app.core.proposal_generator import _missing_sections

    cut = _FULL_PROPOSAL.split("- Beneficio esperado")[0]

    assert _missing_sections(cut) == ["Trade-offs y decisión", "Riesgo o costo"]


def test_build_prompt_requires_a_rag_cited_tradeoff_table_with_three_options():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[
            {"pattern_name": "Capas", "source_role": "primary", "tradeoffs": {}},
            {"pattern_name": "Monolito modular", "source_role": "tradeoff_option", "tradeoffs": {}},
            {"pattern_name": "Microservicios", "source_role": "tradeoff_option", "tradeoffs": {}},
        ],
        prior_content=None,
        feedback=None,
        project_name="P",
    )

    assert "## Trade-offs y decisión" in prompt
    assert "al menos tres filas" in prompt
    assert "Ventajas, Desventajas y Complejidad/costo" in prompt
    assert "Fuente RAG" in prompt
    assert "¿Aprueba los trade-offs?" in prompt


def test_missing_sections_rejects_tradeoff_tables_without_three_options_or_criteria():
    from app.core.proposal_generator import _missing_sections

    incomplete = _FULL_PROPOSAL.replace(
        "| Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Capas | Simple | Escala conjunta | Baja | Alto | [1] |\n"
        "| Modular | Límites claros | Requiere disciplina | Media | Alto | [2] |\n"
        "| Microservicios | Escala independiente | Operación compleja | Alta | Bajo | [3] |",
        "| Opción | Ventajas | Fuente RAG |\n"
        "| --- | --- | --- |\n"
        "| Capas | Simple | [1] |\n"
        "| Modular | Límites claros | [2] |",
    )

    assert _missing_sections(incomplete) == ["Tabla de trade-offs (3 opciones y 3 criterios)"]


def _error_meta(events):
    """(code, retryable) del ultimo evento, que debe ser un ``error`` estructurado."""
    name, payload = events[-1]
    assert name == "error"
    assert set(payload) == {"message", "code", "retryable"}
    assert isinstance(payload["message"], str) and payload["message"]
    return payload["code"], payload["retryable"]


def _drain(gen_iter):
    import asyncio

    async def _run():
        return [event async for event in gen_iter]

    return asyncio.run(_run())


def _stream_with(monkeypatch_target, markdown, finish_reason=None, prompts=None):
    """Corre generate_stream con un modelo falso; devuelve (eventos, persist_calls).

    Si se pasa ``prompts`` (lista), ahi se guarda el prompt que recibio el modelo.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    class _Chunk:
        def __init__(self, content, metadata=None):
            self.content = content
            self.response_metadata = metadata or {}

    class _Model:
        async def astream(self, prompt):
            if prompts is not None:
                prompts.append(prompt)
            yield _Chunk(markdown)
            yield _Chunk("", {"finish_reason": finish_reason} if finish_reason else {})

    persisted = []
    project = SimpleNamespace(name="Biblioteca", description="d")
    with patch.object(gen, "_load_project_and_session", return_value=(project, 1)), \
        patch.object(gen, "load_requirements_text", return_value=""), \
        patch.object(gen, "load_documents_text", return_value=("", [])), \
        patch.object(gen, "_retrieve_patterns", return_value=[]), \
        patch.object(gen, "build_langchain_model", return_value=_Model()), \
        patch.object(gen, "_persist_proposal_and_log",
                     side_effect=lambda **kw: persisted.append(kw) or (7, 8, 1)), \
        patch.object(gen, "_engram_mirror", new=_noop_async):
        events = _drain(
            gen.ProposalGenerator(user_id=1, project_id=1).generate_stream()
        )
    return events, persisted


async def _noop_async(**_kwargs):
    return None


def test_truncated_proposal_is_not_persisted_and_yields_error():
    cut = "## Componentes\n- API Layer - FastAPI\n- Persistence Layer - "

    events, persisted = _stream_with(None, cut)

    assert persisted == []
    assert events[-1][0] == "error"
    assert "incompleta" in events[-1][1]["message"]
    assert _error_meta(events) == ("incomplete_proposal", False)
    assert not any(name == "done" for name, _ in events)


def test_finish_reason_length_is_not_persisted_even_if_sections_exist():
    events, persisted = _stream_with(None, _FULL_PROPOSAL, finish_reason="length")

    assert persisted == []
    assert events[-1][0] == "error"


def test_complete_proposal_is_persisted_and_done_is_emitted():
    events, persisted = _stream_with(None, _FULL_PROPOSAL, finish_reason="stop")

    assert len(persisted) == 1
    assert events[-1][0] == "done"


def test_persisted_prompt_is_the_exact_prompt_sent_to_the_model():
    prompts = []

    events, persisted = _stream_with(
        None, _FULL_PROPOSAL, finish_reason="stop", prompts=prompts
    )

    assert events[-1][0] == "done"
    assert len(prompts) == 1 and len(persisted) == 1
    assert persisted[0]["prompt"] == prompts[0]
    # La latencia medida se guarda en el log (antes quedaba siempre en NULL).
    assert isinstance(persisted[0]["latency_ms"], int) and persisted[0]["latency_ms"] >= 0
    # El log reconstruido antes usaba project_name="" y no llevaba la
    # descripcion: el prompt real si los trae.
    assert "Biblioteca" in persisted[0]["prompt"]


def test_persist_stores_the_given_prompt_in_the_interaction_log():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from app.core import proposal_generator as gen

    db = MagicMock()
    fake_proposal = MagicMock(side_effect=lambda **kw: SimpleNamespace(id=3, **kw))
    fake_log = MagicMock(side_effect=lambda **kw: SimpleNamespace(id=9, **kw))
    long_prompt = "x" * 70000

    with patch.object(gen, "SessionLocal", return_value=db), \
        patch.object(gen, "Proposal", fake_proposal), \
        patch.object(gen, "InteractionLog", fake_log):
        result = gen._persist_proposal_and_log(
            session_id=1,
            project_id=1,
            iteration=1,
            prior_iteration=0,
            prior_proposal_id=None,
            prior_content=None,
            markdown=_FULL_PROPOSAL,
            citations=[],
            feedback=None,
            prompt=long_prompt,
            latency_ms=1234,
        )

    assert result == (3, 9, 1)
    stored = fake_log.call_args.kwargs["prompt"]
    assert stored == long_prompt[:65000]
    assert len(stored) == 65000
    assert fake_log.call_args.kwargs["latency_ms"] == 1234


# --- F10: validador de la tabla de trade-offs (robustez) --------------------

_TABLE_HEADER = (
    "| Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
)
_DECISION_LINES = "- Recomendación: Capas\n- Punto de decisión: ¿Aprueba los trade-offs?\n"


def _proposal_with(table: str, tail: str = _DECISION_LINES) -> str:
    head = _FULL_PROPOSAL.split("## Trade-offs y decisión")[0]
    return head + "## Trade-offs y decisión\n" + table + tail


_ROWS_WITH_SOURCES = (
    "| Capas | Simple | Escala conjunta | Baja | Alto | [1] |\n"
    "| Modular | Límites claros | Requiere disciplina | Media | Alto | [2] |\n"
    "| Microservicios | Escala independiente | Operación compleja | Alta | Bajo | [3] |\n"
)


def test_missing_sections_accepts_header_variants_from_the_llm():
    from app.core.proposal_generator import _missing_sections

    variants = [
        "| Opción | **Ventajas** | **Desventajas** | **Complejidad/costo** |\n| --- | --- | --- | --- |\n",
        "| Opción | Ventajas | Desventajas | Complejidad / costo |\n| --- | --- | --- | --- |\n",
        "| Opción | Ventajas | Desventajas | Complejidad y costo |\n| --- | --- | --- | --- |\n",
        "| Opción | Ventajas | Desventajas | Costo |\n|:---|:---:|---:|---|\n",
    ]
    rows = (
        "| Capas | a | b | Baja |\n| Modular | a | b | Media |\n| Micro | a | b | Alta |\n"
    )
    for header in variants:
        assert _missing_sections(_proposal_with(header + rows)) == [], header


def test_missing_sections_ignores_empty_rows_and_pipes_in_trailing_text():
    from app.core.proposal_generator import _missing_sections

    empty_rows = (
        "| Capas | Simple | Escala conjunta | Baja | Alto | [1] |\n"
        "| | | | | | |\n"
        "| | | | | | |\n"
    )
    assert _missing_sections(_proposal_with(_TABLE_HEADER + empty_rows)) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]

    # Dos filas reales + una linea de texto con "|" tras la tabla: no es una 3a fila.
    two_rows = _ROWS_WITH_SOURCES.splitlines(keepends=True)[:2]
    table = _TABLE_HEADER + "".join(two_rows)
    tail = "- Recomendación: Capas | Modular\n- Punto de decisión: ¿Aprueba los trade-offs?\n"
    assert _missing_sections(_proposal_with(table, tail)) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]


def test_missing_sections_requires_filled_criteria_cells():
    from app.core.proposal_generator import _missing_sections

    blank_criteria = (
        "| Capas | | | | Alto | [1] |\n"
        "| Modular | | | | Alto | [2] |\n"
        "| Micro | | | | Bajo | [3] |\n"
    )
    assert _missing_sections(_proposal_with(_TABLE_HEADER + blank_criteria)) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]


def test_missing_sections_requires_rag_citations_when_sources_were_retrieved():
    from app.core.proposal_generator import _missing_sections

    uncited = (
        "| Capas | Simple | Escala conjunta | Baja | Alto | sin fuente |\n"
        "| Modular | Límites claros | Requiere disciplina | Media | Alto | - |\n"
        "| Micro | Escala independiente | Operación compleja | Alta | Bajo | - |\n"
    )
    proposal = _proposal_with(_TABLE_HEADER + uncited)

    # Sin fuentes recuperadas no se exige [n]; con 3 fuentes sí.
    assert _missing_sections(proposal, source_count=0) == []
    assert _missing_sections(proposal, source_count=3) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]
    # Un [n] fuera de rango (hay 3 fuentes y cita [7]) tampoco vale.
    out_of_range = uncited.replace("sin fuente", "[7]")
    assert _missing_sections(_proposal_with(_TABLE_HEADER + out_of_range), 3) != []
    # Citadas correctamente: ok.
    assert _missing_sections(_proposal_with(_TABLE_HEADER + _ROWS_WITH_SOURCES), 3) == []


def test_missing_sections_accepts_rows_without_source_when_fewer_than_three_sources():
    from app.core.proposal_generator import _missing_sections

    rows = (
        "| Capas | Simple | Escala conjunta | Baja | Alto | [1] |\n"
        "| Modular | Límites claros | Requiere disciplina | Media | Alto | [2] |\n"
        "| Hexagonal | Testeable | Más capas | Media | Medio | Sin fuente RAG |\n"
    )
    assert _missing_sections(_proposal_with(_TABLE_HEADER + rows), source_count=2) == []


def test_missing_sections_requires_recommendation_and_decision_point():
    from app.core.proposal_generator import _missing_sections

    table = _TABLE_HEADER + _ROWS_WITH_SOURCES
    assert _missing_sections(_proposal_with(table, tail=""), 3) == [
        "Recomendación y punto de decisión"
    ]
    only_reco = "- Recomendación: Capas\n"
    assert _missing_sections(_proposal_with(table, tail=only_reco), 3) == [
        "Recomendación y punto de decisión"
    ]


def test_tradeoff_table_is_not_taken_from_a_later_section():
    from app.core.proposal_generator import _missing_sections

    # El encabezado existe pero la tabla esta en OTRA seccion posterior.
    proposal = (
        _FULL_PROPOSAL.split("| Opción")[0]
        + "Sin tabla aqui.\n\n## Anexo\n"
        + _TABLE_HEADER
        + _ROWS_WITH_SOURCES
    )
    assert _missing_sections(proposal) == ["Tabla de trade-offs (3 opciones y 3 criterios)"]


# --- F10: reglas de filas del prompt segun el numero de fuentes -------------


def _citations(n):
    return [
        {
            "pattern_name": f"Patron {i}",
            "source_role": "primary" if i == 1 else "tradeoff_option",
            "tradeoffs": {},
        }
        for i in range(1, n + 1)
    ]


def test_prompt_with_three_sources_demands_one_row_per_source_without_filler():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(_citations(3), None, None, "P")
    assert "Incluye una fila por CADA alternativa [n] recuperada (al menos tres filas)" in prompt
    assert "| ... | ... | ... | ... | ... | [1] |" in prompt
    assert "Sin fuente RAG`" not in prompt


def test_prompt_with_fewer_than_three_sources_allows_marked_filler_rows():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(_citations(2), None, None, "P")
    assert "Solo se recuperaron 2 patrón(es)" in prompt
    assert "`Sin fuente RAG`" in prompt
    assert "al menos tres filas" in prompt
    # Ya no se contradice: no prohibe añadir filas sin [n].
    assert "ni añadas un patrón que no tenga fuente [n]" not in prompt


def test_prompt_without_sources_marks_every_row_as_not_from_rag():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt([], None, None, "P")
    assert "| ... | ... | ... | ... | ... | Sin fuente RAG |" in prompt
    assert "[1] |" not in prompt
    assert "No hay fuentes recuperadas" in prompt


# --- F10: feedback/requerimientos vs. regla dura de escala ------------------

_TIGHT = "MVP en 3 meses, equipo de 4 personas, presupuesto bajo"


def _tight_pool():
    # Microservicios y Event-Driven ganan por similitud; hay mas de 3 candidatos
    # validos, como con los 19 patrones de la base.
    return [
        _pat("Microservicios", 1, 0.98, "alta"),
        _pat("Arquitectura orientada a eventos (Event-Driven)", 2, 0.95, "alta"),
        _pat("Monolito modular (Modular Monolith)", 3, 0.80, "baja"),
        _pat("Arquitectura en capas (Layered)", 4, 0.79, "baja"),
        _pat("Arquitectura hexagonal (Puertos y Adaptadores)", 5, 0.78, "media"),
    ]


def _names(citations):
    return [c["pattern_name"] for c in citations]


def test_team_size_regex_accepts_a_bare_number_but_not_durations():
    from app.core.proposal_generator import _TEAM_SIZE_RE, _normalize_text

    def team(text):
        match = _TEAM_SIZE_RE.search(_normalize_text(text))
        return int(match.group(1)) if match else None

    assert team("MVP en 3 meses, equipo de 4, presupuesto bajo") == 4
    assert team("equipo de 12 personas") == 12
    assert team("equipo de 4 desarrolladores") == 4
    assert team("equipo de 12 meses") is None
    assert team("equipo de 4,5 personas") is None


def test_tight_mvp_with_a_bare_team_number_blocks_distributed_primary():
    from app.core.proposal_generator import _select_citations

    citations = _select_citations(
        _tight_pool(),
        top_n=3,
        min_similarity=0.0,
        explicit_text="MVP en 3 meses, equipo de 4, presupuesto bajo; queremos microservicios",
    )

    assert citations[0]["pattern_name"] == "Monolito modular (Modular Monolith)"


def test_requirement_asking_for_microservices_still_gets_a_discarded_row():
    from app.core.proposal_generator import _select_citations

    citations = _select_citations(
        _tight_pool(),
        top_n=3,
        min_similarity=0.0,
        explicit_text=_TIGHT + "; queremos microservicios",
    )

    assert citations[0]["pattern_name"] == "Monolito modular (Modular Monolith)"
    assert _names(citations)[-1] == "Microservicios"
    assert citations[-1]["scale_disqualified"] is True
    assert "scale_disqualified" not in citations[0]
    # Event-Driven no se pidio: no se cuela como fila fija.
    assert "Arquitectura orientada a eventos (Event-Driven)" not in _names(citations)


def test_feedback_that_changes_to_microservices_beats_the_tight_mvp_rule():
    from app.core.proposal_generator import _select_citations

    citations = _select_citations(
        _tight_pool(),
        top_n=3,
        min_similarity=0.0,
        explicit_text=_TIGHT,
        feedback="cambia a microservicios",
    )

    assert citations[0]["pattern_name"] == "Microservicios"
    assert "scale_disqualified" not in citations[0]


def test_feedback_that_compares_keeps_the_light_primary_and_cites_the_other():
    from app.core.proposal_generator import _select_citations

    citations = _select_citations(
        _tight_pool(),
        top_n=3,
        min_similarity=0.0,
        explicit_text=_TIGHT,
        feedback="comparar monolito modular frente a microservicios",
    )

    assert citations[0]["pattern_name"] == "Monolito modular (Modular Monolith)"
    assert "Microservicios" in _names(citations)
    assert citations[-1]["pattern_name"] == "Microservicios"
    assert citations[-1]["scale_disqualified"] is True


def test_feedback_without_cqrs_drops_it_even_when_pinning_rows():
    from app.core.proposal_generator import _select_citations

    pool = _tight_pool() + [_pat("CQRS (Command Query Responsibility Segregation)", 6, 0.97, "alta")]
    citations = _select_citations(
        pool, top_n=3, min_similarity=0.0, explicit_text=_TIGHT, feedback="sin CQRS"
    )

    assert not any("CQRS" in name for name in _names(citations))


def test_prompt_marks_scale_discarded_rows_and_documents_the_feedback_exception():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[
            {"pattern_name": "Monolito modular", "source_role": "primary", "tradeoffs": {}},
            {"pattern_name": "Capas", "source_role": "tradeoff_option", "tradeoffs": {}},
            {
                "pattern_name": "Microservicios",
                "source_role": "tradeoff_option",
                "tradeoffs": {},
                "scale_disqualified": True,
            },
        ],
        prior_content=None,
        feedback=None,
        project_name="P",
        requirements_text="MVP en 3 meses con equipo de 4 personas",
    )

    block = prompt.split("[3] Microservicios")[1].split("\n\n")[0]
    assert "Descartado por la escala del proyecto" in block
    assert "Descartado por la escala" not in prompt.split("[3] Microservicios")[0]
    assert "si el feedback del usuario pide expresamente cambiar" in prompt
    assert "Consultados no citados" not in prompt


def test_baseline_ignores_microservices_in_requirements_when_primary_is_light():
    from app.core.proposal_generator import _build_prompt

    light_primary = [{"pattern_name": "Monolito modular (Modular Monolith)", "source_role": "primary"}]
    prompt = _build_prompt(
        citations=light_primary,
        prior_content=None,
        feedback=None,
        project_name="P",
        requirements_text="MVP en 3 meses, equipo de 4 personas; queremos microservicios",
    )
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt

    compared = _build_prompt(
        citations=light_primary,
        prior_content=None,
        feedback="comparar monolito modular frente a microservicios",
        project_name="P",
    )
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in compared

    changed = _build_prompt(
        citations=[{"pattern_name": "Microservicios", "source_role": "primary"}],
        prior_content=None,
        feedback="cambia a microservicios",
        project_name="P",
    )
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" in changed


def test_missing_sections_requires_distinct_rag_citations_per_row():
    from app.core.proposal_generator import _missing_sections

    same_source = _FULL_PROPOSAL.replace("| [2] |", "| [1] |").replace("| [3] |", "| [1] |")

    assert _missing_sections(same_source, source_count=3) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]
    assert _missing_sections(_FULL_PROPOSAL, source_count=3) == []


def test_missing_sections_reads_the_rag_column_before_other_cells():
    from app.core.proposal_generator import _missing_sections

    # El [1] en Ventajas no cuenta como cita de la fila si su columna Fuente trae otro.
    proposal = _FULL_PROPOSAL.replace(
        "| Modular | Límites claros | Requiere disciplina | Media | Alto | [2] |",
        "| Modular | Mejor que [1] | Requiere disciplina | Media | Alto | [2] |",
    )

    assert _missing_sections(proposal, source_count=3) == []


# --- F10: encabezados tolerantes, celdas con \| y source_role ---------------

def _with_tradeoff_heading(heading):
    return _FULL_PROPOSAL.replace("## Trade-offs y decisión", heading)


def test_missing_sections_tolerates_decorated_tradeoff_headings():
    from app.core.proposal_generator import _missing_sections

    for heading in (
        "## Trade-offs y decisión",
        "## Trade-offs y decisiones",
        "## 5. Trade-offs y decisión",
        "## **Trade-offs y decisión**",
        "## 5) **Trade-offs y decisión**",
        "### Trade offs y decisión",
        "## Tradeoffs y decisión",
    ):
        proposal = _with_tradeoff_heading(heading)
        assert _missing_sections(proposal, source_count=3) == [], heading


def test_missing_sections_tolerates_reworded_tradeoff_headings():
    # Caso real (Groq gpt-oss-20b): propuesta completa (finish_reason=stop,
    # ~5700 caracteres) descartada solo porque el modelo titulo la seccion de
    # otra forma. El contenido (tabla + punto de decision) se sigue exigiendo.
    from app.core.proposal_generator import _missing_sections

    for heading in (
        "## Trade-offs",
        "## Decisión y trade-offs",
        "## Análisis de trade-offs",
        "## Trade-offs y la decisión",
        "## Alternativas consideradas",
        "## Opciones evaluadas y decisión",
        "## Tradeoffs & decisión",
    ):
        proposal = _with_tradeoff_heading(heading)
        assert _missing_sections(proposal, source_count=3) == [], heading


def test_reworded_tradeoff_heading_still_requires_the_table():
    from app.core.proposal_generator import _missing_sections

    head = _FULL_PROPOSAL.split("## Trade-offs y decisión")[0]
    proposal = head + "## Trade-offs\nNo hay comparación todavía.\n"

    assert _missing_sections(proposal, source_count=3) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]


def test_unrelated_headings_are_not_taken_as_the_tradeoff_section():
    from app.core.proposal_generator import _missing_sections

    head = _FULL_PROPOSAL.split("## Trade-offs y decisión")[0]
    for heading in ("## Decisión final", "## Riesgos", "## Conclusiones"):
        assert "Trade-offs y decisión" in _missing_sections(head + heading + "\nx\n"), heading


def test_missing_sections_tolerates_numbered_or_bold_headings_for_every_section():
    from app.core.proposal_generator import _missing_sections

    proposal = (
        _FULL_PROPOSAL.replace("## Componentes", "## 1. Componentes")
        .replace("## Tecnologias", "## **Tecnologías**")
        .replace("## Patrones", "## 3. Patrones")
        .replace("## Justificación del patrón principal", "## **4. Justificación del patrón principal**")
        .replace("## Trade-offs y decisión", "## 5. Trade-offs y decisión")
    )

    assert _missing_sections(proposal, source_count=3) == []


def test_missing_sections_still_detects_a_really_missing_tradeoff_section():
    from app.core.proposal_generator import _missing_sections

    cut = _FULL_PROPOSAL.split("## Trade-offs y decisión")[0]

    assert _missing_sections(cut, source_count=3) == ["Trade-offs y decisión"]
    # Un texto con la palabra "trade-offs" que no es encabezado no cuenta.
    assert _missing_sections(cut + "Hay trade-offs y decisión pendiente.\n") == ["Trade-offs y decisión"]


def test_table_cells_keep_an_escaped_pipe_inside_the_cell():
    from app.core.proposal_generator import _table_cells

    assert _table_cells("| Capas | Simple \\| rápida | Baja |") == ["Capas", "Simple | rápida", "Baja"]
    assert _table_cells("a | b") == ["a", "b"]
    assert _table_cells("| a | b \\|") == ["a", "b |"]


def test_missing_sections_does_not_shift_columns_when_a_cell_has_an_escaped_pipe():
    from app.core.proposal_generator import _missing_sections

    proposal = _FULL_PROPOSAL.replace(
        "| Capas | Simple | Escala conjunta | Baja | Alto | [1] |",
        "| Capas | Simple \\| rápida | Escala conjunta | Baja | Alto | [1] |",
    )

    assert _missing_sections(proposal, source_count=3) == []


def test_select_citations_marks_non_primary_rows_as_tradeoff_options():
    from app.core.proposal_generator import _select_citations

    citations = _select_citations(_tight_pool(), top_n=3, min_similarity=0.0, explicit_text=_TIGHT)

    assert [c["source_role"] for c in citations] == ["primary", "tradeoff_option", "tradeoff_option"]


# --- Tests que venian de la rama `fixes` (lectura de feedback, baselines por patron, mensajes) ---

def test_build_prompt_tells_the_model_to_decide_instead_of_offering_alternatives():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
    assert "REGLA DE DECISION" in prompt
    # F10: compara alternativas en la tabla y recomienda UNA sola opcion; las
    # formulas ambiguas ("X o Y") solo se admiten dentro de la tabla.
    assert "UNA sola opción" in prompt
    assert "fuera de la tabla" in prompt
    # La regla va antes del formato de salida para que el modelo la vea primero.
    assert prompt.index("REGLA DE DECISION") < prompt.index("Formato OBLIGATORIO")


def test_feedback_stance_reads_common_negations_as_reject():
    from app.core.proposal_generator import _feedback_stance

    for feedback in (
        "no necesitamos microservicios",
        "no quiero que sea microservicios",
        "elimina por completo los microservicios",
        "evitemos los microservicios",
    ):
        assert _feedback_stance("Microservicios", feedback) == "reject", feedback


def test_feedback_stance_unrecognized_mention_is_ambiguous_not_want():
    from app.core.proposal_generator import _feedback_stance

    for feedback in (
        "no cambies a microservicios",
        "no se si usar microservicios",
        "los usuarios de microservicios",
    ):
        assert _feedback_stance("Microservicios", feedback) is None, feedback


def test_feedback_stance_needs_a_positive_signal_to_be_want():
    from app.core.proposal_generator import _feedback_stance

    for feedback in (
        "quiero microservicios",
        "usa microservicios",
        "prefiero microservicios",
        "cambia la arquitectura a microservicios",
        "no uses capas sino microservicios",
        "microservicios en vez de capas",
    ):
        assert _feedback_stance("Microservicios", feedback) == "want", feedback


def test_negated_feedback_does_not_make_microservices_primary_for_a_small_team():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("Microservicios", 1, 0.90, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.80, "baja"),
        _pat("Monolito modular (Modular Monolith)", 3, 0.78, "baja"),
    ]

    for feedback in (
        "no necesitamos microservicios",
        "no quiero que sea microservicios",
        "elimina por completo los microservicios",
    ):
        citations = _select_citations(
            docs,
            top_n=3,
            min_similarity=0.0,
            explicit_text="Equipo de 3 personas",
            feedback=feedback,
        )
        names = [c["pattern_name"] for c in citations]
        assert "Microservicios" not in names, feedback
        assert citations[0]["source_role"] == "primary"


def test_explicitly_requested_ignores_negated_and_hypothetical_mentions():
    from app.core.proposal_generator import _explicitly_requested

    assert not _explicitly_requested(
        "Microservicios", "Restricciones: evitar microservicios; equipo de 3 personas"
    )
    assert not _explicitly_requested("Microservicios", "sin microservicios")
    assert not _explicitly_requested(
        "Microservicios", "a futuro podría migrar a microservicios"
    )
    assert _explicitly_requested("Microservicios", "Necesitamos microservicios por dominio")


def test_requirement_that_avoids_a_pattern_keeps_the_scale_disqualification():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    docs = [
        _pat("Microservicios", 1, 0.95, "alta"),
        _pat("Arquitectura en capas (Layered)", 2, 0.80, "baja"),
    ]
    # Sin penalizacion por complejidad: solo la descalificacion dura puede bajarlo.
    with patch.object(gen, "PROPOSAL_COMPLEXITY_PENALTY", 0.0):
        citations = gen._select_citations(
            docs,
            top_n=2,
            min_similarity=0.0,
            explicit_text="Restricciones: evitar microservicios; equipo de 3 personas",
        )

    assert citations[0]["pattern_name"] == "Arquitectura en capas (Layered)"


def _baseline_head(primary, requirements_text=None, feedback=None):
    from app.core.proposal_generator import _architecture_baseline

    return _architecture_baseline(
        citations=[{"pattern_name": primary, "source_role": "primary"}],
        project_name="P",
        description=None,
        requirements_text=requirements_text,
        prior_content=None,
        feedback=feedback,
    ).split("\n")[0]


def test_baseline_follows_primary_pattern_not_requirement_keywords():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[
            {"pattern_name": "Monolito modular (Modular Monolith)", "source_role": "primary"}
        ],
        prior_content=None,
        feedback=None,
        project_name="P",
        requirements_text="Restricciones: a futuro podría migrar a microservicios",
    )

    assert "ESTRUCTURA BASE SELECCIONADA: monolito modular" in prompt
    assert "ESTRUCTURA BASE SELECCIONADA: microservicios" not in prompt


def test_baseline_has_its_own_case_for_each_catalog_pattern():
    expected = {
        "Serverless (Function-as-a-Service)": "serverless",
        "API Gateway + Backend for Frontend (BFF)": "API Gateway + Backend for Frontend",
        "CQRS (Command Query Responsibility Segregation)": "CQRS",
        "Microservicios": "microservicios",
        "Arquitectura orientada a eventos (Event-Driven)": "orientada a eventos",
        "Arquitectura en capas (Layered)": "arquitectura en capas",
        "Clean Architecture": "Clean Architecture",
        "Monolito modular (Modular Monolith)": "monolito modular",
        "Event sourcing": "event sourcing",
        "Arquitectura hexagonal (Puertos y Adaptadores)": "arquitectura hexagonal",
    }
    for name, label in expected.items():
        assert _baseline_head(name).startswith(
            f"ESTRUCTURA BASE SELECCIONADA: {label}"
        ), name


def test_baseline_covers_every_pattern_in_the_seed_catalog():
    import pathlib

    import yaml

    patterns_dir = pathlib.Path(__file__).resolve().parents[2] / "data" / "patterns"
    names = [
        yaml.safe_load(path.read_text(encoding="utf-8"))["pattern_name"]
        for path in sorted(patterns_dir.glob("*.yaml"))
    ]
    assert len(names) >= 10
    for name in names:
        assert "la propia del patron principal" not in _baseline_head(name), name


def test_baseline_for_unknown_primary_does_not_force_another_style():
    # Un patron fuera del catalogo (Saga ya tiene su propia base desde F10).
    head = _baseline_head("Arquitectura basada en espacios (Space-Based)")

    assert "la propia del patron principal (Arquitectura basada en espacios" in head
    assert "arquitectura en capas" not in head


def test_baseline_fallback_without_primary_ignores_hypothetical_mentions():
    from app.core.proposal_generator import _architecture_baseline

    def _base(**kw):
        return _architecture_baseline(
            citations=[],
            project_name="P",
            description=None,
            requirements_text=kw.get("requirements_text"),
            prior_content=None,
            feedback=kw.get("feedback"),
        ).split("\n")[0]

    assert "microservicios" in _base(feedback="quiero microservicios")
    assert "arquitectura en capas" in _base(
        requirements_text="a futuro podría migrar a microservicios"
    )
    assert "arquitectura en capas" in _base(feedback="no quiero microservicios")


# Seccion de trade-offs valida (la quinta seccion que exige F10), tomada de la
# propuesta completa de los tests de F10.
_TRADEOFFS_BLOCK = _FULL_PROPOSAL[_FULL_PROPOSAL.index("## Trade-offs y decisión"):]


def _proposal_with_risk(label):
    return (
        "## Componentes\n- API\n\n## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patrón principal: Arquitectura en capas (Layered)\n\n"
        "## Justificación del patrón principal\n"
        "- Motivo de elección: reduce el riesgo de acoplamiento.\n"
        "- Reflejo en la arquitectura: ...\n- Beneficio esperado: ...\n"
        f"- {label}: ...\n\n" + _TRADEOFFS_BLOCK
    )


def test_missing_sections_accepts_risk_and_cost_variants():
    from app.core.proposal_generator import _missing_sections

    for label in (
        "Riesgo o costo",
        "Riesgos y costos",
        "Riesgo/costo",
        "**Riesgo o costo**",
        "Riesgo",
    ):
        assert _missing_sections(_proposal_with_risk(label)) == [], label


def test_missing_sections_does_not_take_a_risk_word_from_the_motive_bullet():
    from app.core.proposal_generator import _missing_sections

    cut = _proposal_with_risk("Riesgo o costo").split("- Reflejo")[0]

    # Cortada en la justificacion: faltan el riesgo y (F10) la seccion de trade-offs.
    assert sorted(_missing_sections(cut)) == ["Riesgo o costo", "Trade-offs y decisión"]

    # Un "Riesgo:" dentro de la tabla de trade-offs tampoco cuenta como el de la
    # justificacion: el riesgo se busca antes del encabezado de trade-offs.
    no_risk = _proposal_with_risk("Beneficio extra").replace(
        "## Trade-offs y decisión", "## Trade-offs y decisión\n- Riesgo: algo\n", 1
    )
    assert _missing_sections(no_risk) == ["Riesgo o costo"]


def test_missing_sections_tolerates_singular_and_shorter_headings():
    from app.core.proposal_generator import _missing_sections

    markdown = (
        "## Componente\n- API\n## Tecnología\n- Python\n## Patrón\n- X\n"
        "## Justificación\n- Riesgos y costos: ...\n\n" + _TRADEOFFS_BLOCK
    )

    assert _missing_sections(markdown) == []


def test_incomplete_message_names_the_real_cause():
    from app.core.proposal_generator import _incomplete_proposal_message

    by_length = _incomplete_proposal_message("length", ["Riesgo o costo"])
    by_sections = _incomplete_proposal_message("stop", ["Tecnologias"])

    assert "incompleta" in by_length and "incompleta" in by_sections
    assert "límite de tokens" in by_length
    assert "límite de tokens" not in by_sections
    assert "Tecnologias" in by_sections


def test_complete_proposal_with_variant_headings_is_persisted():
    events, persisted = _stream_with(
        None, _proposal_with_risk("Riesgos y costos"), finish_reason="stop"
    )

    assert len(persisted) == 1
    assert events[-1][0] == "done"


def test_section_error_does_not_blame_the_token_limit():
    events, persisted = _stream_with(
        None, "## Componentes\n- API\n", finish_reason="stop"
    )

    assert persisted == []
    assert events[-1][0] == "error"
    assert "límite de tokens" not in events[-1][1]["message"]

def test_feedback_rules_tell_the_model_to_update_the_tradeoffs_section_too():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[{"pattern_name": "Arquitectura en capas (Layered)", "source_role": "primary"}],
        prior_content=_FULL_PROPOSAL,
        feedback="cambia a capas",
        project_name="P",
    )

    # El cambio debe reflejarse tambien en la tabla y en la Recomendacion, no solo
    # en Componentes/Tecnologias/Patrones/Justificacion.
    assert "Trade-offs y decisión: la tabla y la Recomendación deben reflejar el cambio" in prompt
    assert "Justificacion y la Recomendacion de Trade-offs para el patron nuevo" in prompt

# --- Re-revisión: una negación previa no debe tapar un pedido positivo ------

def test_negation_before_a_positive_switch_does_not_swallow_the_request():
    from app.core.proposal_generator import _explicitly_requested, _feedback_stance

    hexagonal = "Arquitectura hexagonal (Puertos y Adaptadores)"
    assert _feedback_stance("CQRS", "sin CQRS y con hexagonal") == "reject"
    assert _feedback_stance(hexagonal, "sin CQRS y con hexagonal") == "want"
    assert _feedback_stance(hexagonal, "no quiero CQRS y usa hexagonal") == "want"
    assert _explicitly_requested(hexagonal, "Restricciones: sin CQRS y con hexagonal")
    assert not _explicitly_requested("CQRS", "Restricciones: sin CQRS y con hexagonal")


def test_negation_still_covers_a_plain_list_of_patterns():
    from app.core.proposal_generator import _explicitly_requested, _feedback_stance

    # "y" sin marca positiva NO corta la clausula: la negacion sigue aplicando.
    assert not _explicitly_requested("Monolito modular", "evitar microservicios y monolito modular")
    assert _feedback_stance("Monolito modular", "no quiero microservicios y monolito modular") is None

# --- F19: progreso, tope de tiempo y cancelacion (HU primera propuesta < 5 min) ---


def _patched_generator(model, persisted=None):
    """ProposalGenerator con todo lo externo parcheado (devuelve el stream y el contexto)."""
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    persisted = persisted if persisted is not None else []
    project = SimpleNamespace(name="Biblioteca", description="d")
    stack = ExitStack()
    stack.enter_context(patch.object(gen, "_load_project_and_session", return_value=(project, 1)))
    stack.enter_context(patch.object(gen, "load_requirements_text", return_value=""))
    stack.enter_context(patch.object(gen, "load_documents_text", return_value=("", [])))
    stack.enter_context(patch.object(gen, "_retrieve_patterns", return_value=[]))
    stack.enter_context(patch.object(gen, "build_langchain_model", return_value=model))
    stack.enter_context(
        patch.object(
            gen,
            "_persist_proposal_and_log",
            side_effect=lambda **kw: persisted.append(kw) or (7, 8, 1),
        )
    )
    stack.enter_context(patch.object(gen, "_engram_mirror", new=_noop_async))
    return stack, gen.ProposalGenerator(user_id=1, project_id=1), persisted


class _Chunk:
    def __init__(self, content, metadata=None):
        self.content = content
        self.response_metadata = metadata or {}


def test_progress_events_cover_every_stage_in_order_and_never_regress():
    class _Model:
        async def astream(self, _prompt):
            yield _Chunk(_FULL_PROPOSAL)
            yield _Chunk("", {"finish_reason": "stop"})

    stack, generator, _persisted = _patched_generator(_Model())
    with stack:
        events = _drain(generator.generate_stream())

    progress = [payload for name, payload in events if name == "progress"]
    stages = [p["stage"] for p in progress]
    assert stages[0] == "context"
    assert stages[1] == "retrieval"
    assert "generating" in stages
    assert stages[-1] == "saving"
    # El orden de etapas respeta el pipeline y el porcentaje solo sube.
    order = ["context", "retrieval", "generating", "saving"]
    assert [order.index(s) for s in stages] == sorted(order.index(s) for s in stages)
    percents = [p["percent"] for p in progress]
    assert percents == sorted(percents)
    assert percents[-1] < 100  # el 100 % lo marca ``done``, no ``progress``
    assert all(p["elapsed_ms"] >= 0 for p in progress)
    # ``progress`` llega antes que ``done`` y done reporta el tiempo total.
    names = [name for name, _ in events]
    assert names.index("done") > max(i for i, n in enumerate(names) if n == "progress")
    assert events[-1][1]["elapsed_ms"] >= 0


def test_generation_progress_is_throttled_and_tracks_received_chars(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_PROGRESS_INTERVAL_S", 0.0)
    monkeypatch.setattr(gen, "PROPOSAL_EXPECTED_CHARS", 100)

    class _Model:
        async def astream(self, _prompt):
            for _ in range(4):
                yield _Chunk("x" * 20)
            yield _Chunk(_FULL_PROPOSAL, {"finish_reason": "stop"})

    stack, generator, _ = _patched_generator(_Model())
    with stack:
        events = _drain(generator.generate_stream())

    gen_progress = [p for n, p in events if n == "progress" and p["stage"] == "generating" and "chars" in p]
    assert [p["chars"] for p in gen_progress][:4] == [20, 40, 60, 80]
    assert all(20 <= p["percent"] <= 92 for p in gen_progress)


def test_generation_percent_is_bounded():
    from app.core import proposal_generator as gen

    assert gen._generation_percent(0) == 20
    assert gen._generation_percent(10**9) == 92


def test_generation_over_budget_yields_error_and_does_not_persist(monkeypatch):
    import asyncio

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.2)
    closed = []

    class _SlowModel:
        async def astream(self, _prompt):
            try:
                yield _Chunk("## Componentes\n")
                await asyncio.sleep(5)  # el proveedor se cuelga
                yield _Chunk("nunca llega")
            finally:
                closed.append(True)

    stack, generator, persisted = _patched_generator(_SlowModel())
    with stack:
        events = _drain(generator.generate_stream())

    assert persisted == []
    assert events[-1][0] == "error"
    assert "tiempo máximo" in events[-1][1]["message"]
    assert _error_meta(events) == ("timeout", True)
    assert not any(name == "done" for name, _ in events)
    assert closed == [True]  # el stream del LLM se cerro


def test_timeout_of_the_llm_client_is_not_reported_as_our_budget():
    class _Model:
        async def astream(self, _prompt):
            raise TimeoutError("read timeout")
            yield  # pragma: no cover

    stack, generator, persisted = _patched_generator(_Model())
    with stack:
        events = _drain(generator.generate_stream())

    assert persisted == []
    assert events[-1][0] == "error"
    assert "LLM stream failed" in events[-1][1]["message"]
    assert "tiempo máximo" not in events[-1][1]["message"]
    # Un fallo del proveedor es reintentable, pero NO es nuestro tope de tiempo.
    assert _error_meta(events) == ("llm_stream_failed", True)


def test_budget_zero_disables_the_deadline(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0)

    class _Model:
        async def astream(self, _prompt):
            yield _Chunk(_FULL_PROPOSAL)
            yield _Chunk("", {"finish_reason": "stop"})

    stack, generator, persisted = _patched_generator(_Model())
    with stack:
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "done"
    assert len(persisted) == 1
    progress = [p for n, p in events if n == "progress"]
    assert all(p["budget_s"] is None for p in progress)


def test_closing_the_generator_midstream_stops_the_llm_and_persists_nothing():
    """El usuario pulsa Cancelar: el cliente se desconecta y se cierra el generador."""
    import asyncio

    closed = []

    class _Model:
        async def astream(self, _prompt):
            try:
                for _ in range(1000):
                    yield _Chunk("palabra ")
                    await asyncio.sleep(0)
            finally:
                closed.append(True)

    stack, generator, persisted = _patched_generator(_Model())

    async def _run():
        stream = generator.generate_stream()
        seen = 0
        async for name, _payload in stream:
            if name == "token":
                seen += 1
                if seen == 3:
                    break
        await stream.aclose()  # lo que hace Starlette al desconectarse el cliente
        return seen

    with stack:
        seen = asyncio.run(_run())

    assert seen == 3
    assert closed == [True]
    assert persisted == []


# --- F19: el tope de tiempo aplica a TODAS las etapas ----------------------


class _FullModel:
    """Modelo simulado que responde enseguida con una propuesta completa."""

    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    async def astream(self, _prompt):
        self.calls.append(1)
        yield _Chunk(_FULL_PROPOSAL)
        yield _Chunk("", {"finish_reason": "stop"})


def _slow(seconds):
    import time

    def _inner(*_args, **_kwargs):
        time.sleep(seconds)
        return []

    return _inner


def test_within_budget_returns_the_result_with_and_without_deadline():
    import asyncio
    from time import perf_counter

    from app.core import proposal_generator as gen

    async def work():
        return 5

    assert asyncio.run(gen._within_budget(work(), None)) == 5
    assert asyncio.run(gen._within_budget(work(), perf_counter() + 5)) == 5


def test_within_budget_cuts_a_slow_awaitable_and_reports_the_stage():
    import asyncio
    from time import perf_counter

    import pytest

    from app.core import proposal_generator as gen

    async def work():
        await asyncio.sleep(5)

    with pytest.raises(gen._GenerationTimeout) as exc:
        asyncio.run(gen._within_budget(work(), perf_counter() + 0.1, "retrieval"))
    assert exc.value.stage == "retrieval"


def test_within_budget_with_expired_deadline_does_not_start_the_work():
    import asyncio
    from time import perf_counter

    import pytest

    from app.core import proposal_generator as gen

    ran = []

    async def work():
        ran.append(1)

    with pytest.raises(gen._GenerationTimeout):
        asyncio.run(gen._within_budget(work(), perf_counter() - 1, "context"))
    assert ran == []


def test_within_budget_does_not_mask_a_timeout_raised_by_the_work_itself():
    import asyncio
    from time import perf_counter

    import pytest

    from app.core import proposal_generator as gen

    async def work():
        raise TimeoutError("read timeout del cliente")

    with pytest.raises(TimeoutError):
        asyncio.run(gen._within_budget(work(), perf_counter() + 60))


def test_save_reserve_is_a_slice_of_the_budget_never_more_than_20_percent(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_SAVE_RESERVE_S", 10.0)
    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 300.0)
    assert gen._save_reserve_s() == 10.0
    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 15.0)
    assert gen._save_reserve_s() == 3.0
    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0)
    assert gen._save_reserve_s() == 0.0


def test_format_duration_reads_naturally():
    from app.core import proposal_generator as gen

    assert gen._format_duration(300) == "5 min"
    assert gen._format_duration(330) == "5 min 30 s"
    assert gen._format_duration(15) == "15 s"


def test_context_loading_over_budget_yields_error_and_never_calls_the_llm(monkeypatch):
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    calls = []
    stack, generator, persisted = _patched_generator(_FullModel(calls))
    with stack, patch.object(gen, "load_requirements_text", side_effect=_slow(0.9)):
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "error"
    assert "tiempo máximo" in events[-1][1]["message"]
    assert _error_meta(events) == ("timeout", True)
    assert calls == [] and persisted == []
    assert not any(name in {"token", "done"} for name, _ in events)


def test_retrieval_over_budget_yields_error_instead_of_continuing_without_context(monkeypatch):
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    calls = []
    stack, generator, persisted = _patched_generator(_FullModel(calls))
    with stack, patch.object(gen, "_retrieve_patterns", side_effect=_slow(0.9)):
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "error"
    assert "tiempo máximo" in events[-1][1]["message"]
    assert _error_meta(events) == ("timeout", True)
    assert calls == [] and persisted == []
    # Se avisó que se estaba buscando, pero nunca se llegó a redactar.
    stages = [p["stage"] for n, p in events if n == "progress"]
    assert stages[-1] == "retrieval"


def test_saving_over_budget_yields_a_specific_error_and_no_done(monkeypatch):
    import time
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    stack, generator, _ = _patched_generator(_FullModel())

    def _slow_persist(**_kwargs):
        time.sleep(0.9)
        return (7, 8, 1)

    with stack, patch.object(gen, "_persist_proposal_and_log", side_effect=_slow_persist):
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "error"
    assert "guardado" in events[-1][1]["message"]
    # Guardando, la fila pudo quedar escrita: codigo propio (el front rehidrata).
    assert _error_meta(events) == ("save_timeout", True)
    assert not any(name == "done" for name, _ in events)


def test_timeout_message_shows_the_configured_limit_in_readable_form(monkeypatch):
    import asyncio

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)

    class _Hangs:
        async def astream(self, _prompt):
            await asyncio.sleep(60)
            yield _Chunk("nunca")

    stack, generator, _ = _patched_generator(_Hangs())
    with stack:
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "error"
    assert f"({gen._format_duration(0.5)})" in events[-1][1]["message"]
    assert "0 min" not in events[-1][1]["message"]


def test_persist_gets_a_statement_timeout_that_fits_in_the_budget():
    stack, generator, persisted = _patched_generator(_FullModel())
    with stack:
        events = _drain(generator.generate_stream())

    assert events[-1][0] == "done"
    assert 0 < persisted[0]["statement_timeout_ms"] <= 300_000


def test_persist_has_no_statement_timeout_when_the_budget_is_disabled(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0)
    stack, generator, persisted = _patched_generator(_FullModel())
    with stack:
        _drain(generator.generate_stream())

    assert persisted[0]["statement_timeout_ms"] is None


def test_persist_sets_the_statement_timeout_before_writing_anything():
    from unittest.mock import MagicMock, patch

    from app.core import proposal_generator as gen

    db = MagicMock()
    db.add.side_effect = lambda obj: setattr(obj, "id", 1)
    kwargs = dict(
        session_id=1,
        project_id=1,
        iteration=1,
        prior_iteration=0,
        prior_proposal_id=None,
        prior_content=None,
        markdown="m",
        citations=[],
        feedback=None,
        prompt="p",
    )
    with patch.object(gen, "SessionLocal", return_value=db):
        result = gen._persist_proposal_and_log(statement_timeout_ms=1234, **kwargs)

    assert result == (1, 1, 1)
    first_call = db.execute.call_args_list[0]
    assert "statement_timeout" in str(first_call.args[0])
    assert first_call.args[1] == {"ms": "1234"}
    db.commit.assert_called_once()

    db.reset_mock()
    with patch.object(gen, "SessionLocal", return_value=db):
        gen._persist_proposal_and_log(**kwargs)
    db.execute.assert_not_called()


# --- Review PR: errores al guardar --------------------------------------------


class _CompleteModel:
    async def astream(self, _prompt):
        yield _Chunk(_FULL_PROPOSAL)
        yield _Chunk("", {"finish_reason": "stop"})


@pytest.mark.parametrize(
    "message",
    [
        "Has alcanzado el máximo de iteraciones (5)",
        "La propuesta ya no es la última iteración; recarga antes de modificar.",
        "La siguiente iteración no es válida; recarga e intenta de nuevo.",
    ],
)
def test_domain_error_while_saving_keeps_its_specific_message(message):
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    stack, generator, _ = _patched_generator(_CompleteModel())
    with stack, patch.object(
        gen, "_persist_proposal_and_log", side_effect=gen._ProposalDomainError(message)
    ):
        events = _drain(generator.generate_stream())

    assert events[-1] == (
        "error",
        {"message": message, "code": "rejected", "retryable": False},
    )
    assert not any(name == "done" for name, _ in events)


def test_technical_error_while_saving_never_leaks_internal_details():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    leak = "No se pudo persistir la propuesta: (psycopg2.OperationalError) SELECT secret FROM x"
    stack, generator, _ = _patched_generator(_CompleteModel())
    with stack, patch.object(
        gen, "_persist_proposal_and_log", side_effect=gen._ProposalPersistError(leak)
    ):
        events = _drain(generator.generate_stream())

    name, payload = events[-1]
    message = payload["message"]
    assert name == "error"
    assert (payload["code"], payload["retryable"]) == ("save_failed", False)
    assert message.startswith("No se pudo guardar la propuesta")
    assert "psycopg2" not in message and "SELECT" not in message


def test_persist_wraps_infrastructure_failures_as_persist_error_not_domain_error():
    """Un fallo de BD no debe poder confundirse con un error de dominio mostrable."""
    from unittest.mock import MagicMock, patch

    from app.core import proposal_generator as gen

    db = MagicMock()
    db.query.side_effect = RuntimeError("connection reset")
    kwargs = dict(
        session_id=1, project_id=1, iteration=1, prior_iteration=0,
        prior_proposal_id=None, prior_content=None, markdown="m",
        citations=[], feedback=None, prompt="p",
    )
    with patch.object(gen, "SessionLocal", return_value=db):
        with pytest.raises(gen._ProposalPersistError):
            gen._persist_proposal_and_log(**kwargs)

    assert not issubclass(gen._ProposalPersistError, gen._ProposalDomainError)
    db.rollback.assert_called()


# --- Contrato del evento `error` estructurado (review PR) ----------------------
# El front decide el reintento por `retryable`/`code`, nunca por el texto.


def test_error_event_helper_builds_the_documented_payload():
    from app.core import proposal_generator as gen

    assert gen._error_event("boom", gen.ERR_TIMEOUT, retryable=True) == (
        "error",
        {"message": "boom", "code": "timeout", "retryable": True},
    )
    # Por defecto NO es reintentable: hay que optar explicitamente.
    assert gen._error_event("x", gen.ERR_REJECTED)[1]["retryable"] is False


def test_missing_ids_are_invalid_request_and_not_retryable():
    from app.core import proposal_generator as gen

    no_project = _drain(gen.ProposalGenerator(user_id=1).generate_stream())
    no_user = _drain(gen.ProposalGenerator(project_id=1).generate_stream())

    assert _error_meta(no_project) == ("invalid_request", False)
    assert _error_meta(no_user) == ("invalid_request", False)


def test_invalid_llm_config_is_not_retryable():
    from unittest.mock import patch

    from app.core import proposal_generator as gen
    from app.core.llm_loader import LLMConfigError

    stack, generator, persisted = _patched_generator(_CompleteModel())
    with stack, patch.object(
        gen,
        "build_langchain_model",
        side_effect=LLMConfigError("configura GROQ_API_KEY en el backend", reason="not_configured"),
    ):
        events = _drain(generator.generate_stream())

    assert _error_meta(events) == ("llm_config", False)
    # Por SSE llega el mensaje para el usuario, no el detalle del backend.
    message = events[-1][1]["message"]
    assert "GROQ_API_KEY" not in message
    assert "configuración del LLM" in message
    assert persisted == []


def test_llm_without_model_tells_the_user_to_finish_step_3():
    from unittest.mock import patch

    from app.core import proposal_generator as gen
    from app.core.llm_loader import LLMConfigError

    stack, generator, _persisted = _patched_generator(_CompleteModel())
    with stack, patch.object(
        gen, "build_langchain_model", side_effect=LLMConfigError("sin modelo", reason="missing")
    ):
        events = _drain(generator.generate_stream())

    assert "paso 3" in events[-1][1]["message"]


def test_empty_llm_output_is_a_distinct_non_retryable_code():
    class _Empty:
        async def astream(self, _prompt):
            yield _Chunk("")

    stack, generator, persisted = _patched_generator(_Empty())
    with stack:
        events = _drain(generator.generate_stream())

    assert _error_meta(events) == ("llm_empty", False)
    assert persisted == []


def test_domain_error_while_loading_context_is_rejected_and_not_retryable():
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    stack, generator, persisted = _patched_generator(_CompleteModel())
    with stack, patch.object(
        gen, "_load_project_and_session", side_effect=gen._ProposalDomainError("Proyecto no encontrado")
    ):
        events = _drain(generator.generate_stream())

    assert _error_meta(events) == ("rejected", False)
    assert events[-1][1]["message"] == "Proyecto no encontrado"
    assert persisted == []


def test_retryable_never_depends_on_the_wording_of_the_message(monkeypatch):
    """Mismo codigo aunque el texto cambie: el front no puede (ni debe) leerlo."""
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "_format_duration", lambda _s: "SEIS MINUTOS")

    class _Hangs:
        async def astream(self, _prompt):
            import asyncio

            await asyncio.sleep(60)
            yield _Chunk("nunca")

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    stack, generator, _ = _patched_generator(_Hangs())
    with stack:
        events = _drain(generator.generate_stream())

    assert "SEIS MINUTOS" in events[-1][1]["message"]
    assert _error_meta(events) == ("timeout", True)


def test_only_transient_codes_are_retryable():
    """Guarda el contrato de la spec (REQ-13): lista cerrada de codigos reintentables."""
    from app.core import proposal_generator as gen

    transient = {gen.ERR_TIMEOUT, gen.ERR_SAVE_TIMEOUT, gen.ERR_LLM_STREAM}
    permanent = {
        gen.ERR_INVALID_REQUEST,
        gen.ERR_REJECTED,
        gen.ERR_LLM_CONFIG,
        gen.ERR_LLM_EMPTY,
        gen.ERR_INCOMPLETE,
        gen.ERR_SAVE_FAILED,
    }
    assert transient.isdisjoint(permanent)
    assert len(transient | permanent) == 9  # un codigo nuevo obliga a clasificarlo aqui


# --- F19: cancel_event al guardar (no consumir una iteracion huerfana) -----


def _persist_kwargs():
    return dict(
        session_id=1,
        project_id=1,
        iteration=1,
        prior_iteration=0,
        prior_proposal_id=None,
        prior_content=None,
        markdown="m",
        citations=[],
        feedback=None,
        prompt="p",
    )


def test_persist_rolls_back_instead_of_committing_when_cancelled():
    import threading
    from unittest.mock import MagicMock, patch

    import pytest

    from app.core import proposal_generator as gen

    db = MagicMock()
    db.add.side_effect = lambda obj: setattr(obj, "id", 1)
    cancel_event = threading.Event()
    cancel_event.set()

    with patch.object(gen, "SessionLocal", return_value=db):
        with pytest.raises(gen._PersistCancelled):
            gen._persist_proposal_and_log(cancel_event=cancel_event, **_persist_kwargs())

    db.commit.assert_not_called()
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_persist_commits_when_the_cancel_event_is_not_set():
    import threading
    from unittest.mock import MagicMock, patch

    from app.core import proposal_generator as gen

    db = MagicMock()
    db.add.side_effect = lambda obj: setattr(obj, "id", 1)

    with patch.object(gen, "SessionLocal", return_value=db):
        result = gen._persist_proposal_and_log(
            cancel_event=threading.Event(), **_persist_kwargs()
        )

    assert result == (1, 1, 1)
    db.commit.assert_called_once()


def test_cancelling_the_stream_while_saving_marks_the_cancel_event():
    """El hilo de guardado no se puede matar: debe enterarse por el evento."""
    import asyncio
    import threading
    from unittest.mock import patch

    import pytest

    from app.core import proposal_generator as gen

    started = threading.Event()
    seen = {}

    def _persist(**kw):
        seen["event"] = kw["cancel_event"]
        started.set()
        # Simula el hilo ocupado en la BD hasta que el generador lo avisa.
        kw["cancel_event"].wait(timeout=5)
        return (7, 8, 1)

    stack, generator, _ = _patched_generator(_FullModel())

    async def _run():
        async def _consume():
            async for _ in generator.generate_stream():
                pass

        task = asyncio.create_task(_consume())
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with stack, patch.object(gen, "_persist_proposal_and_log", side_effect=_persist):
        asyncio.run(_run())

    assert seen["event"].is_set()


def test_saving_timeout_also_marks_the_cancel_event(monkeypatch):
    import threading
    import time
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_MAX_SECONDS", 0.5)
    seen = {}
    release = threading.Event()

    def _slow_persist(**kw):
        seen["event"] = kw["cancel_event"]
        release.wait(timeout=5)
        time.sleep(0.01)
        return (7, 8, 1)

    stack, generator, _ = _patched_generator(_FullModel())
    with stack, patch.object(gen, "_persist_proposal_and_log", side_effect=_slow_persist):
        events = _drain(generator.generate_stream())
    release.set()

    assert events[-1][0] == "error"
    assert seen["event"].is_set()



# --- Revision del PR: encabezado de trade-offs despues de la justificacion ---


def test_a_subheading_named_options_before_the_justification_is_not_the_tradeoff_section():
    from app.core.proposal_generator import _missing_sections, _tradeoff_section

    proposal = _FULL_PROPOSAL.replace(
        "## Patrones\n",
        "## Patrones\n### Alternativas descartadas\n- Microservicios: muy caro\n\n"
        "## Opciones de despliegue\n- Un VPS\n\n",
    )
    section = _tradeoff_section(proposal)
    assert section is not None
    assert any("| Capas |" in line for line in section)
    assert _missing_sections(proposal, source_count=3) == []


def test_without_justification_only_a_level_two_heading_counts():
    from app.core.proposal_generator import _tradeoff_section

    body = "## Componentes\n- API\n\n### Opciones\n- nada\n"
    assert _tradeoff_section(body) is None
    assert _tradeoff_section(body + "\n## Trade-offs\n| a | b |\n") is not None


# --- Diversidad de familias en las filas de la tabla --------------------------


def test_tradeoff_rows_prefer_alternatives_from_other_families():
    from app.core.proposal_generator import _select_citations

    # Caso real: capas, MVC y monolito modular con similitud 0.84-0.85.
    docs = [
        _pat("Monolito modular (Modular Monolith)", 1, 0.85, "baja"),
        _pat("Arquitectura en capas (Layered)", 2, 0.85, "baja"),
        _pat("MVC / MVVM (Modelo-Vista-Controlador)", 3, 0.84, "baja"),
        _pat("Serverless (Function-as-a-Service)", 4, 0.80, "media"),
        _pat("Microservicios", 5, 0.79, "alta"),
    ]
    citations = _select_citations(docs, top_n=3, min_similarity=0.0)
    names = _names(citations)

    assert names[0] == "Monolito modular (Modular Monolith)"
    assert "Serverless (Function-as-a-Service)" in names
    assert "Microservicios" in names
    assert {c["family"] for c in citations} == {"monolitico", "serverless", "distribuido"}


def test_a_viable_alternative_beats_a_scale_discarded_one_of_a_new_family():
    from app.core.proposal_generator import _select_citations

    docs = [
        _pat("Monolito modular (Modular Monolith)", 1, 0.85, "baja"),
        _pat("Arquitectura en capas (Layered)", 2, 0.84, "baja"),
        _pat("Serverless (Function-as-a-Service)", 3, 0.80, "media"),
        _pat("Microservicios", 4, 0.99, "alta"),
        _pat("Arquitectura orientada a eventos (Event-Driven)", 5, 0.98, "alta"),
    ]
    citations = _select_citations(docs, top_n=3, min_similarity=0.0, explicit_text=_TIGHT)
    names = _names(citations)

    assert names[0] == "Monolito modular (Modular Monolith)"
    assert "Serverless (Function-as-a-Service)" in names
    # Una sola alternativa distribuida (descartada por escala), no las dos.
    distributed = [c for c in citations if c.get("family") == "distribuido"]
    assert len(distributed) == 1
    assert distributed[0]["scale_disqualified"] is True


def test_prompt_shows_the_family_of_each_row():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(
        citations=[
            {"pattern_name": "Monolito modular", "source_role": "primary", "family": "monolitico", "level": "despliegue"},
            {"pattern_name": "Capas", "source_role": "tradeoff_option", "family": "monolitico", "level": "codigo"},
            {"pattern_name": "Serverless", "source_role": "tradeoff_option", "family": "serverless", "level": "despliegue"},
        ],
        prior_content=None,
        feedback=None,
        project_name="P",
    )
    assert "Familia: monolítico" in prompt
    assert "Familia: serverless" in prompt
    assert "se combina con un estilo de despliegue, no lo reemplaza" in prompt
    assert "alternativas REALES" in prompt


def test_prompt_states_the_thresholds_of_the_project_kind():
    from app.core.proposal_generator import _build_prompt

    academic = _build_prompt([], None, None, "P", project_kind="academico")
    enterprise = _build_prompt([], None, None, "P", project_kind="empresarial")
    assert "equipo de hasta 4 personas Y plazo de hasta 3 meses" in academic
    assert "equipo de hasta 2 personas Y plazo de hasta 2 meses" in enterprise


def test_proposal_and_adr_share_the_viability_rules():
    from app.core.adr_generator import ADR_SYSTEM_PROMPT
    from app.core.proposal_generator import _build_prompt
    from app.core.viability_rules import COMMON_VIABILITY_RULES

    assert COMMON_VIABILITY_RULES in _build_prompt([], None, None, "P")
    assert COMMON_VIABILITY_RULES in ADR_SYSTEM_PROMPT


# --- Reparación de una propuesta incompleta (antes había que regenerar) -------

_REPAIR_CITATIONS = [
    {
        "pattern_name": "Monolito modular (Modular Monolith)",
        "source_role": "primary",
        "complexity": "baja",
        "tradeoffs": {"ventajas": ["Un solo despliegue"], "desventajas": ["Escala en bloque"]},
    },
    {
        "pattern_name": "Arquitectura en capas (Layered)",
        "complexity": "baja",
        "tradeoffs": {"ventajas": ["Fácil de entender"], "desventajas": ["Acoplamiento | entre capas"]},
    },
    {
        "pattern_name": "Microservicios",
        "complexity": "alta",
        "scale_disqualified": True,
        "tradeoffs": {"ventajas": ["Escala independiente"], "desventajas": ["Operación compleja"]},
    },
]

# Propuesta real que se descartaba: la tabla quedó con 2 filas y sin punto de decisión.
_BROKEN_TABLE = _FULL_PROPOSAL.replace(
    "| Microservicios | Escala independiente | Operación compleja | Alta | Bajo | [3] |\n", ""
).replace("- Punto de decisión: ¿Aprueba los trade-offs?\n", "")


def test_the_broken_table_is_what_used_to_discard_the_proposal():
    from app.core.proposal_generator import _missing_sections

    assert _missing_sections(_BROKEN_TABLE, source_count=3) == [
        "Tabla de trade-offs (3 opciones y 3 criterios)"
    ]


def test_fallback_table_uses_the_retrieved_patterns_and_passes_validation():
    from app.core.proposal_generator import (
        _fallback_tradeoff_section,
        _merge_proposal_sections,
        _missing_sections,
    )

    proposal = _BROKEN_TABLE
    section = _fallback_tradeoff_section(proposal, _REPAIR_CITATIONS)
    assert section is not None
    rebuilt = _merge_proposal_sections(proposal, section)

    assert _missing_sections(rebuilt, source_count=3) == []
    # La recomendación es el patrón que la propuesta ya eligió (Capas), no la fila 1.
    assert "- Recomendación: Arquitectura en capas (Layered)" in rebuilt
    assert "| Microservicios | Escala independiente | Operación compleja | Alta | Descartada" in rebuilt
    assert "Acoplamiento \\| entre capas" in rebuilt
    # Las demás secciones quedan intactas y en orden.
    assert rebuilt.index("## Justificación") < rebuilt.index("## Trade-offs y decisión")
    assert "- Riesgo o costo: ..." in rebuilt
    assert rebuilt.count("## Trade-offs y decisión") == 1


def test_without_three_sources_there_is_no_fallback_table():
    from app.core.proposal_generator import _fallback_tradeoff_section

    assert _fallback_tradeoff_section(_BROKEN_TABLE, _REPAIR_CITATIONS[:2]) is None


def test_merge_replaces_a_broken_level_three_tradeoff_heading():
    from app.core.proposal_generator import _merge_proposal_sections, _missing_sections

    broken = _BROKEN_TABLE.replace("## Trade-offs y decisión", "### Trade-offs y decisión")
    good_section = "## Trade-offs y decisión" + _FULL_PROPOSAL.split("## Trade-offs y decisión")[1]

    fixed = _merge_proposal_sections(broken, good_section)

    assert "### Trade-offs y decisión" not in fixed
    assert _missing_sections(fixed, source_count=3) == []


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class _RepairModel:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.prompts = reply, error, []

    async def ainvoke(self, prompt):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.reply)


def test_repair_llm_pass_returns_only_the_tradeoffs_and_is_merged():
    from app.core.proposal_generator import _missing_sections, repair_proposal

    tradeoffs = "## Trade-offs y decisión" + _FULL_PROPOSAL.split("## Trade-offs y decisión")[1]
    model = _RepairModel(reply="Aquí está la sección corregida:\n\n" + tradeoffs)

    repaired, how = _run(repair_proposal(model, _BROKEN_TABLE, _REPAIR_CITATIONS))

    assert how == "llm"
    assert _missing_sections(repaired, source_count=3) == []
    assert "Aquí está la sección corregida" not in repaired
    assert "## Componentes\n- API Layer - FastAPI" in repaired
    prompt = model.prompts[0]
    assert "Tabla de trade-offs (3 opciones y 3 criterios)" in prompt
    assert "## Trade-offs y decisión" in prompt and "[3] Microservicios" in prompt


def test_repair_falls_back_to_the_catalog_table_when_the_llm_fails():
    from app.core.proposal_generator import _missing_sections, repair_proposal

    model = _RepairModel(error=RuntimeError("429 rate_limit_exceeded"))

    repaired, how = _run(repair_proposal(model, _BROKEN_TABLE, _REPAIR_CITATIONS))

    assert how == "tabla"
    assert _missing_sections(repaired, source_count=3) == []


def test_repair_falls_back_when_the_llm_answer_is_still_broken():
    from app.core.proposal_generator import repair_proposal

    model = _RepairModel(reply="## Trade-offs y decisión\n| Opción | Ventajas |\n| --- | --- |\n")

    _repaired, how = _run(repair_proposal(model, _BROKEN_TABLE, _REPAIR_CITATIONS))

    assert how == "tabla"


def test_repair_cannot_invent_missing_components():
    from app.core.proposal_generator import repair_proposal

    no_components = _BROKEN_TABLE.replace("## Componentes\n- API Layer - FastAPI\n- Persistence Layer - PostgreSQL\n", "")
    model = _RepairModel(error=RuntimeError("boom"))

    repaired, how = _run(repair_proposal(model, no_components, _REPAIR_CITATIONS))

    assert (repaired, how) == (None, "fallo")


def test_repair_can_be_disabled(monkeypatch):
    from app.core import proposal_generator as gen

    monkeypatch.setattr(gen, "PROPOSAL_REPAIR", False)
    repaired, how = _run(gen.repair_proposal(_RepairModel(), _BROKEN_TABLE, _REPAIR_CITATIONS))

    assert (repaired, how) == (None, "fallo")


def test_a_complete_proposal_is_not_touched():
    from app.core.proposal_generator import repair_proposal

    model = _RepairModel(error=AssertionError("no debe llamar al LLM"))
    repaired, how = _run(repair_proposal(model, _FULL_PROPOSAL, _REPAIR_CITATIONS))

    assert (repaired, how) == (_FULL_PROPOSAL, "ok")


def test_stream_repairs_an_incomplete_table_instead_of_failing():
    """Lo de la demo: antes respondía "incompleta" y había que regenerar."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    no_sources_table = (
        "## Trade-offs y decisión\n"
        "| Opción | Ventajas | Desventajas | Complejidad/costo | Ajuste a requisitos | Fuente RAG |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| Capas | Simple | Escala conjunta | Baja | Alto | Sin fuente RAG |\n"
        "| Modular | Límites claros | Disciplina | Media | Alto | Sin fuente RAG |\n"
        "| Microservicios | Escala | Operación | Alta | Bajo | Sin fuente RAG |\n"
        "- Recomendación: Capas\n"
        "- Punto de decisión: ¿Aprueba los trade-offs?\n"
    )
    broken = _FULL_PROPOSAL.split("## Trade-offs y decisión")[0] + "## Trade-offs y decisión\n| Opción | Ventajas |\n"

    class _Chunk:
        def __init__(self, content, metadata=None):
            self.content = content
            self.response_metadata = metadata or {}

    class _Model:
        async def astream(self, prompt):
            yield _Chunk(broken)
            yield _Chunk("", {"finish_reason": "stop"})

        async def ainvoke(self, prompt):
            if "La validación automática encontró" not in str(prompt):
                raise RuntimeError("solo se espera la pasada de reparación")
            return SimpleNamespace(content=no_sources_table)

    persisted = []
    project = SimpleNamespace(name="Biblioteca", description="d")
    with patch.object(gen, "_load_project_and_session", return_value=(project, 1)), \
        patch.object(gen, "load_requirements_text", return_value=""), \
        patch.object(gen, "load_documents_text", return_value=("", [])), \
        patch.object(gen, "_retrieve_patterns", return_value=[]), \
        patch.object(gen, "build_langchain_model", return_value=_Model()), \
        patch.object(gen, "_persist_proposal_and_log",
                     side_effect=lambda **kw: persisted.append(kw) or (7, 8, 1)), \
        patch.object(gen, "_engram_mirror", new=_noop_async):
        events = _drain(gen.ProposalGenerator(user_id=1, project_id=1).generate_stream())

    assert events[-1][0] == "done"
    assert len(persisted) == 1
    assert "| Microservicios | Escala | Operación | Alta | Bajo | Sin fuente RAG |" in persisted[0]["markdown"]
    stages = [payload["stage"] for name, payload in events if name == "progress"]
    assert "repairing" in stages


def test_a_non_breaking_hyphen_in_the_heading_is_still_the_tradeoff_section():
    """gpt-oss escribe "Trade‑offs" (U+2011) y "Punto de decisión" con U+00A0.

    A la vista es igual, pero la validación no encontraba la sección y la
    propuesta salía como incompleta en cada corrida del proyecto complejo.
    """
    from app.core.proposal_generator import _missing_sections

    proposal = _FULL_PROPOSAL.replace("Trade-offs y decisión", "Trade‑offs y decisión").replace(
        "Punto de decisión", "Punto de decisión"
    )
    assert _missing_sections(proposal, source_count=3) == []
