"""Tests de API para el contexto de proyecto (documentos + propuesta viva).

- GET /api/projects/{id}/proposals/latest: la propuesta ya no vive solo en la
  memoria del front; al volver a entrar a la fase se recupera de la DB.
- POST /elicitation/message: los PDF/MD subidos al proyecto llegan al agente
  (solo se pasa el kwarg si hay documentos, para no cambiar el contrato
  anterior).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.elicitation import ElicitationMessageIn, send_elicitation_message
from app.api.proposals import get_latest_proposal
from app.core import elicitation_agent

CURRENT_USER = {"user_id": 1, "username": "testuser"}


def run(coro):
    return asyncio.run(coro)


def _proposal(lifecycle="approved", iteration=2):
    p = MagicMock()
    p.id = 7
    p.project_id = 1
    p.iteration = iteration
    p.content = "## Componentes\n- API"
    p.citations = [{"pattern_name": "CQRS"}]
    p.feedback = None
    p.lifecycle = lifecycle
    p.created_at = datetime(2026, 9, 28, 12, 0, 0)
    return p


class TestLatestProposal:
    def _db(self, project, proposal):
        db = MagicMock()
        q = db.query.return_value.filter.return_value
        q.first.return_value = project  # _require_owned_project
        q.order_by.return_value.first.return_value = proposal
        return db

    def test_returns_latest_live_proposal(self):
        db = self._db(project=MagicMock(), proposal=_proposal())
        with patch("app.api.proposals.SessionLocal", return_value=db):
            out = run(get_latest_proposal(project_id=1, current_user=CURRENT_USER))

        assert out.id == 7
        assert out.iteration == 2
        assert out.lifecycle == "approved"
        assert out.content.startswith("## Componentes")
        assert out.created_at == "2026-09-28T12:00:00"
        db.close.assert_called_once()

    def test_returns_none_when_there_is_no_live_proposal(self):
        db = self._db(project=MagicMock(), proposal=None)
        with patch("app.api.proposals.SessionLocal", return_value=db):
            assert run(get_latest_proposal(project_id=1, current_user=CURRENT_USER)) is None

    def test_rejected_proposals_are_filtered_in_the_query(self):
        """La consulta debe pedir solo proposed/approved (una rechazada no se
        rehidrata: tras rechazar se espera generar una nueva)."""
        db = self._db(project=MagicMock(), proposal=None)
        with patch("app.api.proposals.SessionLocal", return_value=db):
            run(get_latest_proposal(project_id=1, current_user=CURRENT_USER))
        criteria = " ".join(str(c) for c in db.query.return_value.filter.call_args.args)
        assert "lifecycle IN" in criteria

    def test_foreign_or_missing_project_is_rejected(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [None, None]
        with patch("app.api.proposals.SessionLocal", return_value=db):
            with pytest.raises(HTTPException) as exc:
                run(get_latest_proposal(project_id=99, current_user=CURRENT_USER))
        assert exc.value.status_code == 404


def _project(description="Un CRM"):
    project = MagicMock()
    project.id = 1
    project.user_id = 1
    project.description = description
    project.phase_ready = False
    return project


def _state_with_history():
    # Función (no constante): el endpoint muta el engram_state que carga.
    return {
        "engram_state": {"1": {"requerimientos": {
            "preguntas_respuestas": [{"pregunta": "p1", "respuesta": "r1"}],
            "pending_question": "pendiente",
            "resumen": None,
        }}}
    }


class TestElicitationReceivesDocuments:
    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.get_langfuse_handler", return_value=None)
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    @patch("app.api.elicitation.load_documents_text")
    @patch("app.core.elicitation_agent.generate_summary")
    @patch("app.core.elicitation_agent.next_step")
    def test_documents_are_passed_to_next_step_and_summary(
        self, mock_next, mock_summary, mock_docs, mock_load, mock_require,
        mock_build, _mock_handler, _mock_save,
    ):
        mock_require.return_value = _project()
        mock_load.return_value = _state_with_history()
        mock_build.return_value = MagicMock()
        mock_docs.return_value = ("### Documento: acta.md\nplazo de 8 meses", ["acta.md"])
        mock_next.return_value = elicitation_agent.ElicitationDecision(True, None, "ok")
        mock_summary.return_value = {"problema": "x"}

        result = run(send_elicitation_message(
            project_id=1, body=ElicitationMessageIn(answer="respuesta"), current_user=CURRENT_USER,
        ))

        assert result.done is True
        assert "plazo de 8 meses" in mock_next.call_args.kwargs["documents_context"]
        assert "plazo de 8 meses" in mock_summary.call_args.kwargs["documents_context"]

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.get_langfuse_handler", return_value=None)
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    @patch("app.api.elicitation.load_documents_text", return_value=("", []))
    @patch("app.core.elicitation_agent.next_step")
    def test_no_documents_means_no_extra_kwarg(
        self, mock_next, _mock_docs, mock_load, mock_require, mock_build,
        _mock_handler, _mock_save,
    ):
        mock_require.return_value = _project()
        mock_load.return_value = _state_with_history()
        mock_build.return_value = MagicMock()
        mock_next.return_value = elicitation_agent.ElicitationDecision(False, "otra?", "ok")

        run(send_elicitation_message(
            project_id=1, body=ElicitationMessageIn(answer="respuesta"), current_user=CURRENT_USER,
        ))

        assert "documents_context" not in mock_next.call_args.kwargs


class TestElicitationAgentPrompts:
    def test_documents_section_is_added_to_the_context(self):
        model = MagicMock()
        model.invoke.return_value = MagicMock(content='{"problema": "p", "usuarios": "u", '
                                                      '"funcionalidades": [], "restricciones": [], "calidad": []}')
        elicitation_agent.generate_summary(
            model, [{"pregunta": "q", "respuesta": "a"}], "desc",
            documents_context="### Documento: acta.md\nplazo de 8 meses",
        )
        sent = model.invoke.call_args.args[0][1].content
        assert "plazo de 8 meses" in sent

    def test_no_documents_leaves_context_unchanged(self):
        model = MagicMock()
        model.invoke.return_value = MagicMock(content='{"problema": "p", "usuarios": "u", '
                                                      '"funcionalidades": [], "restricciones": [], "calidad": []}')
        elicitation_agent.generate_summary(model, [{"pregunta": "q", "respuesta": "a"}], "desc")
        sent = model.invoke.call_args.args[0][1].content
        assert "Documentos aportados" not in sent
