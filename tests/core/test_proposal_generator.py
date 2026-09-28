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


def test_build_prompt_with_citations_asks_for_bracket_numbers():
    from app.core.proposal_generator import _build_prompt

    citations = [{"pattern_name": "CQRS", "snippet": "separa lectura y escritura"}]
    prompt = _build_prompt(
        citations=citations, prior_content=None, feedback=None, project_name="P"
    )
    assert "[1] CQRS" in prompt
    assert "cita el numero entre corchetes" in prompt
