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
    assert "NO uses numeros entre corchetes" in prompt


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
    assert citations[1]["source_role"] == "consulted_not_cited"
    assert "Patrón principal: <nombre>" in prompt
    assert "Consultados no citados: Saga" in prompt
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
            {"pattern_name": "Microservicios", "source_role": "consulted_not_cited"},
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
            {"pattern_name": "Monolito modular", "source_role": "consulted_not_cited", "tradeoffs": {}},
            {"pattern_name": "Microservicios", "source_role": "consulted_not_cited", "tradeoffs": {}},
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


def _drain(gen_iter):
    import asyncio

    async def _run():
        return [event async for event in gen_iter]

    return asyncio.run(_run())


def _stream_with(monkeypatch_target, markdown, finish_reason=None):
    """Corre generate_stream con un modelo falso; devuelve (eventos, persist_calls)."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.core import proposal_generator as gen

    class _Chunk:
        def __init__(self, content, metadata=None):
            self.content = content
            self.response_metadata = metadata or {}

    class _Model:
        async def astream(self, _prompt):
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
    assert "incompleta" in events[-1][1]
    assert not any(name == "done" for name, _ in events)


def test_finish_reason_length_is_not_persisted_even_if_sections_exist():
    events, persisted = _stream_with(None, _FULL_PROPOSAL, finish_reason="length")

    assert persisted == []
    assert events[-1][0] == "error"


def test_complete_proposal_is_persisted_and_done_is_emitted():
    events, persisted = _stream_with(None, _FULL_PROPOSAL, finish_reason="stop")

    assert len(persisted) == 1
    assert events[-1][0] == "done"
