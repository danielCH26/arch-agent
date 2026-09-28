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
