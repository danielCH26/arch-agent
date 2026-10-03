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
    MAX_QUESTIONS,
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

    def test_first_question_uses_relevant_documents_when_available(self):
        model = _FakeModel([
            '{"done": false, "question": "El acta define el alcance. ¿Qué usuario atenderá primero?", "reason": "faltan usuarios"}'
        ])

        decision = next_step(
            model,
            history=[],
            project_description="Sistema de inventario",
            documents_context=(
                "### Documento: acta.md\nEl sistema debe registrar inventario de "
                "bodegas. Presupuesto de 10 millones COP. Equipo de 3 personas. "
                "Plazo de 3 meses."
            ),
        )

        assert decision.done is False
        assert "usuario" in (decision.question or "").lower()
        assert len(model.calls) == 1
        prompt_context = model.calls[0][1].content
        assert "inventario de bodegas" in prompt_context
        assert "No hay respuestas todavía" in prompt_context


class TestNextStepHardRules:
    def test_forces_not_done_before_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert decision.question is not None

    def test_respects_done_after_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ok"}'])
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context="Presupuesto definido. Equipo disponible. Plazo acordado.",
        )
        assert decision.done is True

    def test_forces_done_at_max_questions(self):
        model = _FakeModel(['{"done": false, "question": "otra", "reason": "sigo"}'])
        decision = next_step(
            model,
            history=HISTORY_10,
            documents_context="Presupuesto definido. Equipo disponible. Plazo acordado.",
        )
        assert decision.done is True

    def test_requires_budget_team_and_timeline_before_finishing(self):
        history = [
            {"pregunta": f"pregunta {index}", "respuesta": "respuesta detallada"}
            for index in range(5)
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])

        decision = next_step(model, history=history)

        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()
        assert "viabilidad" in decision.reason

    def test_allows_finishing_when_viability_factors_are_known(self):
        history = [
            {"pregunta": "usuarios", "respuesta": "Operadores de bodega."},
            {"pregunta": "funciones", "respuesta": "Registrar inventario."},
            {"pregunta": "presupuesto", "respuesta": "Presupuesto máximo de 20 millones COP."},
            {"pregunta": "equipo", "respuesta": "Equipo de 3 desarrolladores senior."},
            {"pregunta": "plazo", "respuesta": "MVP en 12 semanas."},
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])

        decision = next_step(model, history=history)

        assert decision.done is True


class TestNextStepParsingEdgeCases:
    def test_handles_fence_without_json_tag(self):
        model = _FakeModel(['```\n{"done": false, "question": "¿otra?", "reason": "x"}\n```'])
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context="Presupuesto definido. Equipo disponible. Plazo acordado.",
        )
        assert decision.question == "¿otra?"

    def test_handles_think_block_before_json(self):
        model = _FakeModel(
            ['<think>pensando mucho</think>\n{"done": true, "question": null, "reason": "listo"}']
        )
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context="Presupuesto definido. Equipo disponible. Plazo acordado.",
        )
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


# --- Verificación de viabilidad (review #5 y #6) ---------------------------

from app.core.elicitation_agent import (  # noqa: E402
    _VIABILITY_FACTORS,
    _missing_viability_factors,
)


def _missing(history, description="", documents=None):
    return [name for name, _ in _missing_viability_factors(history, description, documents)]


class TestMissingViabilityFactors:
    def test_generic_question_text_does_not_cover_team_or_deadline(self):
        history = [
            {"pregunta": "¿Cuántas personas usarán el sistema?", "respuesta": "Unas 50"},
            {"pregunta": "¿Qué tiempo de respuesta esperan?", "respuesta": "Menos de 2 s"},
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_question_text_alone_never_counts(self):
        history = [
            {"pregunta": "¿Cuál es el presupuesto, el equipo y el plazo?", "respuesta": "No sé"},
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_keywords_need_word_boundaries(self):
        history = [
            {
                "pregunta": "p",
                "respuesta": "Reservas de mesa, una promesa de servicio y hacemos copia diaria",
            }
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_accented_words_are_recognized(self):
        history = [
            {"pregunta": "p", "respuesta": "Una inversión de 5.000 dólares"},
            {"pregunta": "p", "respuesta": "Equipo de 2 desarrolladores"},
            {"pregunta": "p", "respuesta": "Entrega en 3 meses"},
        ]
        assert _missing(history) == []

    def test_monthly_cost_and_real_time_are_not_a_deadline(self):
        history = [
            {"pregunta": "p", "respuesta": "Máximo 100 USD al mes. Equipo de 3."},
            {"pregunta": "p", "respuesta": "Necesitamos notificaciones en tiempo real"},
        ]
        assert _missing(history) == ["plazo"]

    def test_description_and_documents_still_count(self):
        assert _missing(
            [],
            "Presupuesto bajo",
            "Equipo de 3 personas. Plazo de 3 meses.",
        ) == []

    def test_answering_the_viability_question_with_unknown_closes_the_factor(self):
        budget_question = _VIABILITY_FACTORS[0][2]
        history = [{"pregunta": budget_question, "respuesta": "Aún no lo definimos"}]
        assert _missing(history) == ["equipo", "plazo"]


class TestViabilityRuleGating:
    def test_does_not_replace_the_llm_question_in_early_turns(self):
        for size in (1, 2, 3, 4):
            history = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(size)]
            model = _FakeModel(
                ['{"done": false, "question": "¿Qué usuarios tendrá?", "reason": "x"}']
            )
            decision = next_step(model, history=history)
            assert decision.question == "¿Qué usuarios tendrá?", size
            assert decision.done is False

    def test_applies_when_the_llm_wants_to_finish_early(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()

    def test_applies_once_the_minimum_is_reached(self):
        model = _FakeModel(
            ['{"done": false, "question": "otra", "reason": "sigo"}']
        )
        decision = next_step(model, history=HISTORY_5)
        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()
        assert "viabilidad" in decision.reason

    def test_never_asks_an_eleventh_question(self):
        model = _FakeModel(['{"done": false, "question": "otra", "reason": "sigo"}'])
        decision = next_step(model, history=HISTORY_10)
        assert decision.done is True
        assert decision.question is None

    def test_vague_answers_never_exceed_max_questions(self):
        model_response = '{"done": false, "question": "¿Qué usuarios tendrá?", "reason": "x"}'
        history = []
        for _ in range(MAX_QUESTIONS + 2):
            decision = next_step(_FakeModel([model_response]), history=history)
            if decision.done:
                break
            history.append({"pregunta": decision.question, "respuesta": "no sé"})
        assert decision.done is True
        assert len(history) == MAX_QUESTIONS
