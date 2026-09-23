"""
Tests de integración (mocked) para /api/projects/{id}/elicitation/*.

Cubren lo que quedaba fuera de tests/core/test_elicitation_agent.py (que
solo prueba el agente en aislamiento): las rutas HTTP en sí, en particular
- el aislamiento del estado por proyecto (_project_key / anidado en
  engram_state) -- el bug que hacía que dos proyectos del mismo usuario se
  pisaran entre sí.
- los códigos de estado de cada rama de error.
- que approve/modify/reject escriban lo que corresponde en `approvals` y
  dejen `phase_ready` en el valor correcto.

Mocking puro (sin TestClient ni DB real), igual que el resto de tests/api/.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.elicitation import (
    ElicitationDecisionIn,
    ElicitationMessageIn,
    decide_elicitation,
    get_elicitation_state,
    send_elicitation_message,
)
from app.core import elicitation_agent
from app.core.llm_loader import LLMConfigError


def run(coro):
    return asyncio.run(coro)


CURRENT_USER = {"user_id": 1, "username": "testuser"}


def make_project(project_id=1, description="Un CRM interno"):
    project = MagicMock()
    project.id = project_id
    project.user_id = CURRENT_USER["user_id"]
    project.description = description
    project.phase_ready = False
    return project


class TestGetElicitationState:
    """GET /api/projects/{id}/elicitation"""

    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_no_session_yet_returns_empty_state(self, mock_load, mock_require):
        mock_require.return_value = make_project()
        mock_load.return_value = None

        result = run(get_elicitation_state(project_id=1, current_user=CURRENT_USER))

        assert result.done is False
        assert result.question is None
        assert result.resumen is None
        assert result.history == []

    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_pending_question_is_returned(self, mock_load, mock_require):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [],
                "pending_question": "¿Quiénes usarán el sistema?",
                "resumen": None,
            }}}
        }

        result = run(get_elicitation_state(project_id=1, current_user=CURRENT_USER))

        assert result.done is False
        assert result.question == "¿Quiénes usarán el sistema?"

    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_resumen_present_means_done(self, mock_load, mock_require):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": None,
                "resumen": {"problema": "x", "usuarios": "y", "funcionalidades": [],
                            "restricciones": [], "calidad": []},
            }}}
        }

        result = run(get_elicitation_state(project_id=1, current_user=CURRENT_USER))

        assert result.done is True
        assert result.resumen["problema"] == "x"

    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_project_isolation_does_not_leak_between_projects(self, mock_load, mock_require):
        """
        Bug encontrado en revisión de PR: sessions es una fila por usuario,
        no por proyecto. Si engram_state se indexara solo por fase, el
        proyecto 2 vería el resumen del proyecto 1 (o viceversa).
        """
        mock_require.side_effect = lambda user_id, project_id: make_project(project_id)
        mock_load.return_value = {
            "engram_state": {
                "1": {"requerimientos": {
                    "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                    "pending_question": None,
                    "resumen": {"problema": "proyecto uno", "usuarios": "", "funcionalidades": [],
                                "restricciones": [], "calidad": []},
                }},
                "2": {"requerimientos": {
                    "preguntas_respuestas": [],
                    "pending_question": "¿Qué problema resuelve el proyecto 2?",
                    "resumen": None,
                }},
            }
        }

        result_1 = run(get_elicitation_state(project_id=1, current_user=CURRENT_USER))
        result_2 = run(get_elicitation_state(project_id=2, current_user=CURRENT_USER))

        assert result_1.done is True
        assert result_1.resumen["problema"] == "proyecto uno"
        assert result_2.done is False
        assert result_2.question == "¿Qué problema resuelve el proyecto 2?"
        assert result_2.resumen is None


class TestSendElicitationMessage:
    """POST /api/projects/{id}/elicitation/message"""

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_first_call_returns_forced_first_question_without_llm(
        self, mock_load, mock_require, mock_build_model, mock_save
    ):
        """Historial vacío -> FIRST_QUESTION determinística, sin llamar al LLM."""
        mock_require.return_value = make_project()
        mock_load.return_value = None
        mock_build_model.return_value = MagicMock()

        result = run(send_elicitation_message(
            project_id=1, body=ElicitationMessageIn(), current_user=CURRENT_USER
        ))

        assert result.done is False
        assert result.question == elicitation_agent.FIRST_QUESTION
        mock_build_model.return_value.invoke.assert_not_called()

    @patch("app.api.elicitation.flush_langfuse")
    @patch("app.api.elicitation.get_langfuse_handler")
    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    @patch("app.core.elicitation_agent.next_step")
    def test_flushes_langfuse_after_a_real_llm_call(
        self, mock_next_step, mock_load, mock_require, mock_build_model,
        mock_save, mock_get_handler, mock_flush,
    ):
        """Regresión (PR #79 review): una llamada real al LLM en elicitación
        debe exportar la traza de inmediato, no depender solo del ciclo en
        segundo plano del SDK de Langfuse."""
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "pregunta pendiente",
                "resumen": None,
            }}}
        }
        mock_build_model.return_value = MagicMock()
        mock_get_handler.return_value = MagicMock()  # Langfuse "configurado"
        mock_next_step.return_value = elicitation_agent.ElicitationDecision(
            done=False, question="siguiente pregunta", reason="sigue"
        )

        run(send_elicitation_message(
            project_id=1, body=ElicitationMessageIn(answer="respuesta 2"),
            current_user=CURRENT_USER,
        ))

        mock_flush.assert_called_once()

    @patch("app.api.elicitation.flush_langfuse")
    @patch("app.api.elicitation.get_langfuse_handler")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    @patch("app.core.elicitation_agent.next_step")
    def test_flushes_langfuse_even_when_the_llm_call_fails(
        self, mock_next_step, mock_load, mock_require, mock_build_model,
        mock_get_handler, mock_flush,
    ):
        """La traza de una llamada fallida tambien debe exportarse -- por
        eso el flush vive en un ``finally``, no solo en el camino feliz."""
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "pregunta pendiente",
                "resumen": None,
            }}}
        }
        mock_build_model.return_value = MagicMock()
        mock_get_handler.return_value = MagicMock()
        mock_next_step.side_effect = elicitation_agent.ElicitationLLMError("rate limit")

        with pytest.raises(HTTPException):
            run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="respuesta 2"),
                current_user=CURRENT_USER,
            ))

        mock_flush.assert_called_once()

    @patch("app.api.elicitation.load_session_state")
    def test_400_when_resumen_already_generated(self, mock_load):
        with patch("app.api.elicitation._require_project", return_value=make_project()):
            mock_load.return_value = {
                "engram_state": {"1": {"requerimientos": {
                    "preguntas_respuestas": [],
                    "pending_question": None,
                    "resumen": {"problema": "x"},
                }}}
            }

            with pytest.raises(HTTPException) as exc_info:
                run(send_elicitation_message(
                    project_id=1, body=ElicitationMessageIn(answer="algo"),
                    current_user=CURRENT_USER,
                ))

        assert exc_info.value.status_code == 400
        assert "decision" in exc_info.value.detail

    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_400_when_answering_without_pending_question(self, mock_load, mock_require):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [],
                "pending_question": None,
                "resumen": None,
            }}}
        }

        with pytest.raises(HTTPException) as exc_info:
            run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="una respuesta"),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 400
        assert "pendiente" in exc_info.value.detail

    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_re_asks_pending_question_without_calling_llm_when_no_answer(
        self, mock_load, mock_require, mock_build_model
    ):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "¿Y las restricciones de tiempo?",
                "resumen": None,
            }}}
        }

        result = run(send_elicitation_message(
            project_id=1, body=ElicitationMessageIn(), current_user=CURRENT_USER
        ))

        assert result.question == "¿Y las restricciones de tiempo?"
        mock_build_model.assert_not_called()

    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_409_when_llm_not_configured(self, mock_load, mock_require, mock_build_model):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "pregunta pendiente",
                "resumen": None,
            }}}
        }
        mock_build_model.side_effect = LLMConfigError("sin config")

        with pytest.raises(HTTPException) as exc_info:
            run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="respuesta 2"),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 409

    @patch("app.api.elicitation.elicitation_agent.next_step")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_503_when_llm_call_fails(self, mock_load, mock_require, mock_build_model, mock_next_step):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "pregunta pendiente",
                "resumen": None,
            }}}
        }
        mock_build_model.return_value = MagicMock()
        mock_next_step.side_effect = elicitation_agent.ElicitationLLMError("rate limit")

        with pytest.raises(HTTPException) as exc_info:
            run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="respuesta 2"),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 503

    @patch("app.api.elicitation.elicitation_agent.next_step")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_502_when_model_returns_invalid_json(
        self, mock_load, mock_require, mock_build_model, mock_next_step
    ):
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                "pending_question": "pregunta pendiente",
                "resumen": None,
            }}}
        }
        mock_build_model.return_value = MagicMock()
        mock_next_step.side_effect = elicitation_agent.ElicitationAgentError(
            "El modelo no devolvió JSON válido: ..."
        )

        with pytest.raises(HTTPException) as exc_info:
            run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="respuesta 2"),
                current_user=CURRENT_USER,
            ))

        # El detalle debe ser accionable para el usuario, no el error técnico crudo.
        assert exc_info.value.status_code == 502
        assert "JSON" not in exc_info.value.detail
        assert "modelo de ia" in exc_info.value.detail.lower()

    @patch("app.api.elicitation.elicitation_agent.next_step")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_project_isolation_when_saving_new_state(
        self, mock_load, mock_require, mock_build_model, mock_next_step
    ):
        """
        Responder en el proyecto 1 no debe pisar (ni leer) el estado del
        proyecto 2 dentro del mismo engram_state compartido por el usuario.
        """
        mock_require.side_effect = lambda user_id, project_id: make_project(project_id)
        shared_engram_state = {
            "2": {"requerimientos": {
                "preguntas_respuestas": [{"pregunta": "otra", "respuesta": "otra"}],
                "pending_question": None,
                "resumen": {"problema": "proyecto dos", "usuarios": "", "funcionalidades": [],
                            "restricciones": [], "calidad": []},
            }}
        }
        mock_load.return_value = {
            "engram_state": {
                "1": {"requerimientos": {
                    "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
                    "pending_question": "¿algo más?",
                    "resumen": None,
                }},
                **shared_engram_state,
            }
        }
        mock_build_model.return_value = MagicMock()
        mock_next_step.return_value = elicitation_agent.ElicitationDecision(
            done=False, question="siguiente pregunta", reason="sigue"
        )

        saved_state = {}

        def fake_save(user_id, project_id, active_phase, engram_state):
            saved_state.update(engram_state)

        with patch("app.api.elicitation.save_session_state", side_effect=fake_save):
            result = run(send_elicitation_message(
                project_id=1, body=ElicitationMessageIn(answer="respuesta a la pregunta"),
                current_user=CURRENT_USER,
            ))

        assert result.question == "siguiente pregunta"
        # El estado del proyecto 2 se conserva intacto tras guardar el del proyecto 1.
        assert saved_state["2"]["requerimientos"]["resumen"]["problema"] == "proyecto dos"
        assert saved_state["1"]["requerimientos"]["pending_question"] == "siguiente pregunta"


class TestDecideElicitation:
    """POST /api/projects/{id}/elicitation/decision"""

    def test_400_modify_without_feedback(self):
        with pytest.raises(HTTPException) as exc_info:
            run(decide_elicitation(
                project_id=1,
                body=ElicitationDecisionIn(decision="modify", feedback=None),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 400
        assert "feedback" in exc_info.value.detail.lower()

    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_400_when_no_active_session(self, mock_require, mock_session_local):
        mock_require.return_value = make_project()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_local.return_value = mock_db

        with pytest.raises(HTTPException) as exc_info:
            run(decide_elicitation(
                project_id=1,
                body=ElicitationDecisionIn(decision="approve"),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 400

    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_400_when_no_resumen_yet(self, mock_require, mock_session_local):
        mock_require.return_value = make_project()
        session_row = MagicMock()
        session_row.id = 10
        session_row.engram_state = {"1": {"requerimientos": {
            "preguntas_respuestas": [], "pending_question": "algo", "resumen": None,
        }}}
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = session_row
        mock_session_local.return_value = mock_db

        with pytest.raises(HTTPException) as exc_info:
            run(decide_elicitation(
                project_id=1,
                body=ElicitationDecisionIn(decision="approve"),
                current_user=CURRENT_USER,
            ))

        assert exc_info.value.status_code == 400

    def _session_row_with_resumen(self, project_id=1, session_id=10):
        session_row = MagicMock()
        session_row.id = session_id
        session_row.engram_state = {str(project_id): {"requerimientos": {
            "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
            "pending_question": None,
            "resumen": {"problema": "x", "usuarios": "y", "funcionalidades": [],
                        "restricciones": [], "calidad": []},
        }}}
        return session_row

    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_approve_sets_phase_ready_and_logs_approval(self, mock_require, mock_session_local):
        project = make_project()
        mock_require.return_value = project
        session_row = self._session_row_with_resumen()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [session_row, project]
        mock_session_local.return_value = mock_db

        result = run(decide_elicitation(
            project_id=1,
            body=ElicitationDecisionIn(decision="approve"),
            current_user=CURRENT_USER,
        ))

        assert result.decision == "approve"
        assert result.phase_ready is True
        assert project.phase_ready is True

        added = mock_db.add.call_args[0][0]
        assert added.session_id == session_row.id
        assert added.phase == "requerimientos"
        assert added.decision == "approved"
        mock_db.commit.assert_called_once()

    @patch("app.api.elicitation.flag_modified")
    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_modify_reopens_phase_and_keeps_phase_ready_false(
        self, mock_require, mock_session_local, mock_flag_modified
    ):
        project = make_project()
        project.phase_ready = True  # sanity: debe volver a False
        mock_require.return_value = project
        session_row = self._session_row_with_resumen()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [session_row, project]
        mock_session_local.return_value = mock_db

        result = run(decide_elicitation(
            project_id=1,
            body=ElicitationDecisionIn(decision="modify", feedback="Faltó hablar de seguridad"),
            current_user=CURRENT_USER,
        ))

        assert result.decision == "modify"
        assert result.phase_ready is False
        assert project.phase_ready is False

        added = mock_db.add.call_args[0][0]
        assert added.decision == "modified"
        assert added.feedback == "Faltó hablar de seguridad"

        # El resumen se descarta y se reabre la fase para seguir preguntando.
        new_phase_data = session_row.engram_state["1"]["requerimientos"]
        assert new_phase_data["resumen"] is None
        assert new_phase_data["pending_question"] is None
        assert new_phase_data["preguntas_respuestas"][-1]["respuesta"] == "Faltó hablar de seguridad"

    @patch("app.api.elicitation.flag_modified")
    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_reject_clears_phase_state_and_keeps_phase_ready_false(
        self, mock_require, mock_session_local, mock_flag_modified
    ):
        project = make_project()
        mock_require.return_value = project
        session_row = self._session_row_with_resumen()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [session_row, project]
        mock_session_local.return_value = mock_db

        result = run(decide_elicitation(
            project_id=1,
            body=ElicitationDecisionIn(decision="reject"),
            current_user=CURRENT_USER,
        ))

        assert result.decision == "reject"
        assert result.phase_ready is False
        assert project.phase_ready is False

        added = mock_db.add.call_args[0][0]
        assert added.decision == "rejected"

        assert session_row.engram_state["1"]["requerimientos"] == {}

    @patch("app.api.elicitation.SessionLocal")
    @patch("app.api.elicitation._require_project")
    def test_decision_does_not_touch_other_projects_state(self, mock_require, mock_session_local):
        """Rechazar la elicitación del proyecto 1 no debe tocar el proyecto 2."""
        project = make_project(project_id=1)
        mock_require.return_value = project
        session_row = self._session_row_with_resumen(project_id=1)
        session_row.engram_state["2"] = {"requerimientos": {
            "preguntas_respuestas": [],
            "pending_question": None,
            "resumen": {"problema": "proyecto dos", "usuarios": "", "funcionalidades": [],
                        "restricciones": [], "calidad": []},
        }}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [session_row, project]
        mock_session_local.return_value = mock_db

        with patch("app.api.elicitation.flag_modified"):
            run(decide_elicitation(
                project_id=1,
                body=ElicitationDecisionIn(decision="reject"),
                current_user=CURRENT_USER,
            ))

        assert session_row.engram_state["1"]["requerimientos"] == {}
        assert session_row.engram_state["2"]["requerimientos"]["resumen"]["problema"] == "proyecto dos"
