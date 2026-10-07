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
    assert "tiempo máximo" in events[-1][1]
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
    assert "LLM stream failed" in events[-1][1]
    assert "tiempo máximo" not in events[-1][1]


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
    assert "tiempo máximo" in events[-1][1]
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
    assert "tiempo máximo" in events[-1][1]
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
    assert "guardado" in events[-1][1]
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
    assert f"({gen._format_duration(0.5)})" in events[-1][1]
    assert "0 min" not in events[-1][1]


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


# --- Review F19 #2: "Cancelar" no debe dejar una iteración guardada ----------


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

    assert events[-1] == ("error", message)
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

    name, message = events[-1]
    assert name == "error"
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
        citations=[], feedback=None,
    )
    with patch.object(gen, "SessionLocal", return_value=db):
        with pytest.raises(gen._ProposalPersistError):
            gen._persist_proposal_and_log(**kwargs)

    assert not issubclass(gen._ProposalPersistError, gen._ProposalDomainError)
    db.rollback.assert_called()
