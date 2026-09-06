import json
from unittest.mock import MagicMock

from app.core.elicitation_agent import FIRST_QUESTION, generate_summary, next_step


def _model_response(payload: dict) -> MagicMock:
    model = MagicMock()
    model.invoke.return_value.content = json.dumps(payload)
    return model


def test_elicitation_starts_with_an_open_question_without_calling_llm():
    model = MagicMock()

    decision = next_step(model, [])

    assert decision.question == FIRST_QUESTION
    assert decision.done is False
    model.invoke.assert_not_called()


def test_elicitation_does_not_finish_before_minimum_questions():
    model = _model_response({"done": True, "question": None, "reason": "enough"})
    history = [{"pregunta": f"P{i}", "respuesta": f"R{i}"} for i in range(4)]

    decision = next_step(model, history)

    assert decision.done is False
    assert decision.question


def test_summary_keeps_the_four_reviewable_requirement_categories():
    expected = {
        "problema": "Reducir tiempos de atención",
        "usuarios": "Clientes y agentes de soporte",
        "funcionalidades": ["Crear tickets"],
        "restricciones": ["Entregar en tres meses"],
        "calidad": ["Disponibilidad 99.9%"],
    }

    summary = generate_summary(
        _model_response(expected),
        [{"pregunta": "¿Qué necesitan?", "respuesta": "Soporte"}],
    )

    assert summary == expected
