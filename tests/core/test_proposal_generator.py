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
    ]


def test_missing_sections_detects_a_cut_inside_the_justification():
    from app.core.proposal_generator import _missing_sections

    cut = _FULL_PROPOSAL.split("- Beneficio esperado")[0]

    assert _missing_sections(cut) == ["Riesgo o costo"]


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


# --- Negaciones en el feedback y en los requerimientos (review #2 y #3) ------


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


# --- La estructura base sale del patron principal (review #4) ---------------


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
    head = _baseline_head("Saga")

    assert "la propia del patron principal (Saga)" in head
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


# --- Verificacion de propuesta completa (review #7) -------------------------


def _proposal_with_risk(label):
    return (
        "## Componentes\n- API\n\n## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patrón principal: Arquitectura en capas (Layered)\n\n"
        "## Justificación del patrón principal\n"
        "- Motivo de elección: reduce el riesgo de acoplamiento.\n"
        "- Reflejo en la arquitectura: ...\n- Beneficio esperado: ...\n"
        f"- {label}: ...\n"
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

    assert _missing_sections(cut) == ["Riesgo o costo"]


def test_missing_sections_tolerates_singular_and_shorter_headings():
    from app.core.proposal_generator import _missing_sections

    markdown = (
        "## Componente\n- API\n## Tecnología\n- Python\n## Patrón\n- X\n"
        "## Justificación\n- Riesgos y costos: ...\n"
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
    assert "límite de tokens" not in events[-1][1]


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
