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


def test_build_prompt_tells_the_model_to_decide_instead_of_offering_alternatives():
    from app.core.proposal_generator import _build_prompt

    prompt = _build_prompt(citations=[], prior_content=None, feedback=None, project_name="P")
    assert "REGLA DE DECISION" in prompt
    assert "UNA sola opcion" in prompt
    assert "no le pidas al usuario que elija" in prompt
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
