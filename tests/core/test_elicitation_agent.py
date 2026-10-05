"""
Tests para el agente de elicitación (parseo de JSON del LLM, reglas duras
de preguntas, y manejo de errores del proveedor).

Issue: [F05] Elicitación guiada + aprobación
Revisión de PR #63: agrega el caso de fence sin la palabra 'json' que
faltaba cubrir con un test unitario.
"""

import logging

import pytest

from app.core.elicitation_agent import (
    ElicitationAgentError,
    ElicitationLLMError,
    FIRST_QUESTION,
    _es_pregunta_compuesta,
    _extract_json_object,
    _strip_json_fences,
    generate_summary,
    next_step,
    NEXT_STEP_SYSTEM_PROMPT,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    """Modelo LangChain simulado: responde en orden con lo que se le indique."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _FakeMessage(response)


HISTORY_1 = [{"pregunta": "p0", "respuesta": "r0"}]
HISTORY_5 = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(5)]
HISTORY_10 = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(10)]


class TestStripJsonFences:
    def test_fence_with_json_tag(self):
        raw = '```json\n{"done": true}\n```'
        assert _strip_json_fences(raw) == '{"done": true}'

    def test_fence_without_json_tag(self):
        # Caso señalado en revisión de PR #63: sin la palabra 'json', el
        # '\n' no debe quedar pegado al JSON.
        raw = '```\n{"done": true}\n```'
        assert _strip_json_fences(raw) == '{"done": true}'

    def test_no_fence_at_all(self):
        raw = '{"done": false}'
        assert _strip_json_fences(raw) == '{"done": false}'


class TestExtractJsonObject:
    def test_extracts_from_think_block(self):
        raw = '<think>razonando...</think>\n{"done": true}'
        assert _extract_json_object(raw) == '{"done": true}'

    def test_extracts_with_surrounding_prose(self):
        raw = 'aquí va: {"done": false, "question": "¿algo?"} gracias'
        assert _extract_json_object(raw) == '{"done": false, "question": "¿algo?"}'

    def test_returns_text_unchanged_if_no_braces(self):
        assert _extract_json_object("sin json aquí") == "sin json aquí"


class TestEsPreguntaCompuesta:
    def test_dos_bloques_interrogativos_apilados_son_compuestos(self):
        pregunta = (
            "¿Quiénes son los usuarios principales? "
            "¿Qué funcionalidades críticas necesitan?"
        )
        assert _es_pregunta_compuesta(pregunta) is True

    def test_pregunta_granular_no_es_compuesta(self):
        assert _es_pregunta_compuesta(
            "¿Quiénes son los usuarios principales del sistema?"
        ) is False

    def test_y_dentro_de_un_solo_bloque_interrogativo_no_es_compuesto(self):
        # Falso positivo a evitar: una sola interrogación con "y" interno
        # tiene UN solo '?' -- ese caso lo cubren las reglas del prompt,
        # no este detector (Issue #100: heurística deliberadamente angosta).
        pregunta = (
            "¿Quiénes son los usuarios principales y qué funcionalidades "
            "críticas necesitan?"
        )
        assert _es_pregunta_compuesta(pregunta) is False

    def test_sin_cierres_interrogativos_no_es_compuesta(self):
        assert _es_pregunta_compuesta("") is False
        assert _es_pregunta_compuesta("Cuéntame más sobre las restricciones") is False

    def test_tipo_inesperado_no_rompe_y_no_es_compuesta(self):
        # Fail-open: un tipo inesperado no debe romper el flujo del agente.
        assert _es_pregunta_compuesta(None) is False


class TestNextStepPromptGranularidad:
    """Issue #100 opción A: el prompt prohíbe explícitamente la pregunta
    compuesta y exige granularidad (el prompt ES el artefacto, el test de
    contenido es legítimo acá)."""

    def test_prompt_prohibe_pregunta_compuesta_y_exige_una_dimension(self):
        assert "UNA sola dimensión" in NEXT_STEP_SYSTEM_PROMPT
        assert "Prohibida la pregunta compuesta" in NEXT_STEP_SYSTEM_PROMPT

    def test_prompt_exige_granularidad_respondible_en_una_o_dos_oraciones(self):
        assert "una o dos oraciones" in NEXT_STEP_SYSTEM_PROMPT

    def test_prompt_incluye_ejemplo_compuesto_malo(self):
        assert "MALA (compuesta)" in NEXT_STEP_SYSTEM_PROMPT
        assert (
            "¿Quiénes son los usuarios principales y qué funcionalidades "
            "críticas necesitan?" in NEXT_STEP_SYSTEM_PROMPT
        )

    def test_prompt_incluye_ejemplo_granular_bueno(self):
        assert "BUENA (granular)" in NEXT_STEP_SYSTEM_PROMPT
        assert (
            "¿Quiénes son los usuarios principales del sistema?"
            in NEXT_STEP_SYSTEM_PROMPT
        )

    def test_prompt_mantiene_las_4_categorias_y_contrato_json(self):
        # Regresión: las reglas nuevas no reemplazan lo existente.
        for categoria in ("Usuarios", "Funcionalidades", "Restricciones", "Calidad"):
            assert categoria in NEXT_STEP_SYSTEM_PROMPT
        assert '"done": bool' in NEXT_STEP_SYSTEM_PROMPT
        assert '"question"' in NEXT_STEP_SYSTEM_PROMPT


PREGUNTA_COMPUESTA = (
    "¿Quiénes son los usuarios principales? "
    "¿Qué funcionalidades críticas necesitan?"
)
PREGUNTA_GRANULAR = "¿Quiénes son los usuarios principales del sistema?"


class TestNextStepRetryPreguntaCompuesta:
    """Issue #100 opción C: una pregunta evidentemente compuesta dispara
    UN reintento correctivo; si el reintento devuelve una pregunta
    granular, se usa esa."""

    def test_pregunta_compuesta_dispara_reintento_y_usa_la_granular(self):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        decision = next_step(model, history=HISTORY_5)
        assert decision.done is False
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 2

    def test_reintento_reusa_el_mismo_contexto_con_instruccion_correctiva(self):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        next_step(model, history=HISTORY_5)
        mensajes_reintento = model.calls[1]
        contexto = mensajes_reintento[1].content
        assert "UNA sola pregunta sobre UN solo tema" in contexto
        # El historial original viaja en el reintento (mismo seam de invocación).
        assert "p0" in contexto


class TestNextStepFailOpenPreguntaCompuesta:
    """Fail-open (Issue #100): si el reintento no arregla la pregunta, se
    devuelve la original con warning -- nunca se eleva un error al usuario."""

    def test_reintento_tambien_compuesto_devuelve_original_con_warning(self, caplog):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR} ¿seguro?", "reason": "y"}}',
            ]
        )
        with caplog.at_level(logging.WARNING, logger="app.core.elicitation_agent"):
            decision = next_step(model, history=HISTORY_5)
        assert decision.question == PREGUNTA_COMPUESTA
        assert len(model.calls) == 2
        assert "compuesta" in caplog.text.lower()
        assert PREGUNTA_COMPUESTA in caplog.text

    def test_reintento_no_parseable_devuelve_original_sin_raise(self, caplog):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                "esto no es json",
            ]
        )
        with caplog.at_level(logging.WARNING, logger="app.core.elicitation_agent"):
            decision = next_step(model, history=HISTORY_5)
        assert decision.question == PREGUNTA_COMPUESTA
        assert len(model.calls) == 2
        assert "compuesta" in caplog.text.lower()


class TestNextStepSinReintento:
    """Regresión (Issue #100): el guardarraíl no debe agregar llamadas al
    LLM cuando no hay pregunta compuesta, ni en los caminos deterministas."""

    def test_pregunta_granular_hace_una_sola_llamada(self):
        model = _FakeModel(
            [f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "x"}}']
        )
        decision = next_step(model, history=HISTORY_5)
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 1

    def test_pregunta_compuesta_al_maximo_se_fuerza_done_sin_reintento(self):
        # Al llegar al máximo la regla dura fuerza done=True y descarta la
        # pregunta: reintentar sería una llamada desperdiciada.
        model = _FakeModel(
            [f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}']
        )
        decision = next_step(model, history=HISTORY_10)
        assert decision.done is True
        assert decision.question is None
        assert len(model.calls) == 1

    def test_compuesta_forzada_por_minimo_tambien_se_reintenta(self):
        # done=true antes del mínimo conserva la pregunta del modelo (acá
        # compuesta); la regla dura la deja en done=False y el reintento
        # opera sobre la decisión final.
        model = _FakeModel(
            [
                f'{{"done": true, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 2


class TestNextStepFirstQuestion:
    def test_first_question_is_deterministic_and_skips_llm(self):
        model = _FakeModel([])  # no debe consumirse ninguna respuesta
        decision = next_step(model, history=[])
        assert decision.done is False
        assert decision.question == FIRST_QUESTION
        assert model.calls == []


class TestNextStepHardRules:
    def test_forces_not_done_before_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert decision.question is not None

    def test_respects_done_after_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ok"}'])
        decision = next_step(model, history=HISTORY_5)
        assert decision.done is True

    def test_forces_done_at_max_questions(self):
        model = _FakeModel(['{"done": false, "question": "otra", "reason": "sigo"}'])
        decision = next_step(model, history=HISTORY_10)
        assert decision.done is True


class TestNextStepParsingEdgeCases:
    def test_handles_fence_without_json_tag(self):
        model = _FakeModel(['```\n{"done": false, "question": "¿otra?", "reason": "x"}\n```'])
        decision = next_step(model, history=HISTORY_5)
        assert decision.question == "¿otra?"

    def test_handles_think_block_before_json(self):
        model = _FakeModel(
            ['<think>pensando mucho</think>\n{"done": true, "question": null, "reason": "listo"}']
        )
        decision = next_step(model, history=HISTORY_5)
        assert decision.done is True

    def test_raises_on_invalid_json(self):
        model = _FakeModel(["esto no es json"])
        with pytest.raises(ElicitationAgentError):
            next_step(model, history=HISTORY_5)


class TestLLMErrorHandling:
    def test_provider_exception_becomes_elicitation_llm_error(self):
        model = _FakeModel([RuntimeError("Error code: 429 - rate_limit_exceeded")])
        with pytest.raises(ElicitationLLMError):
            next_step(model, history=HISTORY_5)

    def test_elicitation_llm_error_is_subclass_of_agent_error(self):
        assert issubclass(ElicitationLLMError, ElicitationAgentError)


class TestGenerateSummary:
    def test_parses_summary_shape(self):
        model = _FakeModel(
            [
                '{"problema": "x", "usuarios": "y", "funcionalidades": [], '
                '"restricciones": [], "calidad": []}'
            ]
        )
        summary = generate_summary(model, history=HISTORY_5)
        assert summary["problema"] == "x"
        assert set(summary.keys()) == {
            "problema", "usuarios", "funcionalidades", "restricciones", "calidad"
        }
