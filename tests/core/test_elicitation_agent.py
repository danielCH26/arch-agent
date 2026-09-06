"""
Tests para el agente de elicitación (parseo de JSON del LLM, reglas duras
de preguntas, y manejo de errores del proveedor).

Issue: [F05] Elicitación guiada + aprobación
Revisión de PR #63: agrega el caso de fence sin la palabra 'json' que
faltaba cubrir con un test unitario.
"""

import pytest

from app.core.elicitation_agent import (
    ElicitationAgentError,
    ElicitationLLMError,
    FIRST_QUESTION,
    _extract_json_object,
    _strip_json_fences,
    generate_summary,
    next_step,
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
