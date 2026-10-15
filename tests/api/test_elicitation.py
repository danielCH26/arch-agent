"""Contract tests para POST /api/projects/{project_id}/elicitation/decision.

Hallazgo #8 (revisión feature/hu6-diagrama): antes, `decide_elicitation`
cortaba con 400 ("No hay una sesión de elicitación activa...") si todavía
no existía una `UserSession`, un criterio distinto al de
`proposals.py`/`diagrams.py` (que la crean de forma perezosa vía
`record_approval_decision`). No había ningún test de API para este
endpoint -- estos tests fijan el contrato correcto:

- Sin `UserSession` (o sin resumen todavía) -> 400, mismo mensaje que "no
  hay resumen que aprobar" (no un 400 aparte por sesión faltante, y sobre
  todo no un 500 por `session_row` en `None`).
- Con resumen -> approve/modify/reject funcionan y persisten en
  `approvals` con `project_id` (hallazgo #1), igual que diagrams.py.

Mismo patrón que tests/api/test_diagrams.py: SQLite in-memory + monkeypatch
de `SessionLocal` en los módulos que la routa realmente usa.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.elicitation import (
    ElicitationMessageIn,
    get_elicitation_state,
    send_elicitation_message,
)
from app.core import database, elicitation_agent
from app.core.database import Base
from app.core.llm_loader import LLMConfigError

PHASE = "requerimientos"  # AVAILABLE_PHASES[0] en app/api/projects.py

_TEST_TABLES = ["users", "sessions", "projects", "approvals"]

# --- Helpers para TestGetElicitationState / TestSendElicitationMessage -----
# (mocking puro, sin TestClient ni DB real -- igual que el resto de
# tests/api/ antes de la migración a `fake_db` que usa TestDecideElicitation)

CURRENT_USER = {"user_id": 1, "username": "testuser"}


def run(coro):
    return asyncio.run(coro)


def make_project(project_id=1, description="Un CRM interno"):
    project = MagicMock()
    project.id = project_id
    project.user_id = CURRENT_USER["user_id"]
    project.description = description
    project.phase_ready = False
    return project


@pytest.fixture()
def fake_db():
    """Spin up an in-memory SQLite y patchea `SessionLocal` en los TRES
    lugares que `decide_elicitation` termina usando:

    - `app.api.elicitation.SessionLocal`: la propia ruta (`db = SessionLocal()`).
    - `app.core.session_store.SessionLocal`: usado por `record_approval_decision`.
    - `app.core.database.SessionLocal`: `_require_project` (app/api/projects.py)
      hace `from app.core.database import SessionLocal` DENTRO de la función en
      cada llamada, así que alcanza con patchear el atributo del módulo.

    A diferencia de test_diagrams.py, acá no hace falta el parche de
    JSONB->JSON: `sessions.engram_state` ya usa el tipo genérico `JSON` de
    SQLAlchemy (ver app/models/session.py), y `approvals`/`projects`/`users`
    no tienen columnas JSON(B).
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401

    for table_name in _TEST_TABLES:
        Base.metadata.tables[table_name].create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    real_session_local = database.SessionLocal

    with patch("app.api.elicitation.SessionLocal", Session), \
         patch("app.core.session_store.SessionLocal", Session):
        database.SessionLocal = Session
        try:
            yield Session, engine
        finally:
            database.SessionLocal = real_session_local

    engine.dispose()


def _seed_user_and_project(fake_db, *, user_id: int, project_id: int, project_name: str = "P"):
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.user import User
        from app.models.project import Project

        if db.query(User).filter(User.id == user_id).first() is None:
            db.add(User(id=user_id, username=f"u{user_id}", email=f"u{user_id}@x", password_hash="x"))
        db.add(Project(id=project_id, user_id=user_id, name=project_name))
        db.commit()
    finally:
        db.close()


def _seed_session_with_resumen(
    fake_db,
    *,
    user_id: int,
    project_id: int,
    resumen: dict | None = None,
    history: list[dict] | None = None,
):
    """Simula el estado que deja POST /elicitation/message al terminar:
    una `UserSession` con `engram_state[project_id][PHASE].resumen` seteado.
    """
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.session import UserSession

        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        engram_state = dict(session_row.engram_state) if session_row and session_row.engram_state else {}
        engram_state[str(project_id)] = {
            PHASE: {
                "preguntas_respuestas": history or [{"pregunta": "¿Qué problema resuelve?", "respuesta": "Gestión de pedidos"}],
                "pending_question": None,
                "resumen": resumen if resumen is not None else {"contexto": "Sistema de gestión de pedidos"},
            }
        }
        if session_row is None:
            db.add(UserSession(user_id=user_id, engram_state=engram_state))
        else:
            session_row.engram_state = engram_state
        db.commit()
    finally:
        db.close()


def _client_for_user(user_id: int = 1, username: str = "alice"):
    from fastapi import FastAPI
    from app.api.elicitation import router as elicitation_router

    app = FastAPI()
    app.include_router(elicitation_router)

    async def fake_current_user():
        return {"user_id": user_id, "username": username}

    deps = __import__("app.api.dependencies", fromlist=["get_current_user"])
    app.dependency_overrides = {deps.get_current_user: fake_current_user}
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /{project_id}/elicitation/decision
# ---------------------------------------------------------------------------


class TestDecideElicitation:
    def test_without_any_user_session_returns_400_not_500(self, fake_db):
        """Hallazgo #8 (corrección post-revisión): antes, sin `UserSession`,
        se cortaba con un 400 ("no hay sesión activa") ANTES de intentar
        nada más. Ahora la ausencia de sesión se trata igual que la
        ausencia de resumen -- mismo código y mismo mensaje -- y sobre
        todo no debe explotar con un 500 al tocar `session_row.engram_state`
        en las ramas de modify/reject."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.session import UserSession

            assert db.query(UserSession).filter(UserSession.user_id == 1).first() is None
        finally:
            db.close()

        client = _client_for_user(user_id=1)
        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "approve"}
        )

        assert response.status_code == 400
        assert "resumen" in response.json()["detail"].lower()

    def test_without_resumen_yet_returns_400(self, fake_db):
        """Con `UserSession` ya creada pero sin resumen todavía (fase en
        curso), sigue siendo 400 -- mismo criterio, ahora la sesión sí
        existe pero el resumen no."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.session import UserSession

            db.add(UserSession(user_id=1, engram_state={}))
            db.commit()
        finally:
            db.close()

        client = _client_for_user(user_id=1)
        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "approve"}
        )

        assert response.status_code == 400
        assert "resumen" in response.json()["detail"].lower()

    def test_approve_persists_approval_row_with_project_id(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_session_with_resumen(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "approve"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "approve"
        assert body["phase_ready"] is True

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.approval import Approval
            from app.models.project import Project

            rows = db.query(Approval).filter(Approval.phase == PHASE).all()
            assert len(rows) == 1
            assert rows[0].decision == "approved"
            assert rows[0].project_id == 1

            project = db.query(Project).filter(Project.id == 1).first()
            assert project.phase_ready is True
        finally:
            db.close()

    def test_modify_requires_feedback(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_session_with_resumen(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "modify"}
        )

        assert response.status_code == 400

    def test_modify_with_feedback_reopens_phase_and_clears_resumen(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_session_with_resumen(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/elicitation/decision",
            json={"decision": "modify", "feedback": "faltó el flujo de pagos"},
        )

        assert response.status_code == 200
        assert response.json()["phase_ready"] is False

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.session import UserSession

            session_row = db.query(UserSession).filter(UserSession.user_id == 1).first()
            phase_data = session_row.engram_state["1"][PHASE]
            assert phase_data["resumen"] is None
            assert phase_data["preguntas_respuestas"][-1]["respuesta"] == "faltó el flujo de pagos"
        finally:
            db.close()

    def test_reject_resets_phase_data(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_session_with_resumen(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "reject"}
        )

        assert response.status_code == 200
        assert response.json()["phase_ready"] is False

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.session import UserSession

            session_row = db.query(UserSession).filter(UserSession.user_id == 1).first()
            assert session_row.engram_state["1"][PHASE] == {}
        finally:
            db.close()

    def test_approving_project_a_does_not_leak_into_project_b(self, fake_db):
        """Hallazgo #1: la decisión de un proyecto no debe filtrarse ni
        marcar `phase_ready` de otro proyecto del mismo usuario."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1, project_name="A")
        _seed_user_and_project(fake_db, user_id=1, project_id=2, project_name="B")
        _seed_session_with_resumen(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/elicitation/decision", json={"decision": "approve"}
        )
        assert response.status_code == 200

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.approval import Approval
            from app.models.project import Project

            rows = db.query(Approval).filter(Approval.phase == PHASE).all()
            assert len(rows) == 1
            assert rows[0].project_id == 1

            project_b = db.query(Project).filter(Project.id == 2).first()
            assert project_b.phase_ready is False
        finally:
            db.close()

    def test_404_for_unknown_project(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/999/elicitation/decision", json={"decision": "approve"}
        )

        assert response.status_code == 404

    def test_403_for_cross_user_project(self, fake_db):
        """A diferencia de diagrams.py/chat.py (que reimplementan su propio
        chequeo de ownership devolviendo 404 para no filtrar existencia),
        `decide_elicitation` usa `_require_project` de app/api/projects.py,
        que devuelve 403 -- no 404 -- cuando el proyecto existe pero es de
        otro usuario. Este test fija ese contrato tal cual es hoy."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=2, project_id=2, project_name="P2")
        _seed_session_with_resumen(fake_db, user_id=2, project_id=2)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/2/elicitation/decision", json={"decision": "approve"}
        )

        assert response.status_code == 403


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

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.flush_langfuse")
    @patch("app.api.elicitation.get_langfuse_handler")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    @patch("app.core.elicitation_agent.next_step")
    def test_flushes_langfuse_even_when_the_llm_call_fails(
        self, mock_next_step, mock_load, mock_require, mock_build_model,
        mock_get_handler, mock_flush, mock_save,
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

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_409_when_llm_not_configured(self, mock_load, mock_require, mock_build_model, mock_save):
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

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.elicitation_agent.next_step")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_503_when_llm_call_fails(self, mock_load, mock_require, mock_build_model, mock_next_step, mock_save):
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

    @patch("app.api.elicitation.save_session_state")
    @patch("app.api.elicitation.elicitation_agent.next_step")
    @patch("app.api.elicitation.build_langchain_model")
    @patch("app.api.elicitation._require_project")
    @patch("app.api.elicitation.load_session_state")
    def test_502_when_model_returns_invalid_json(
        self, mock_load, mock_require, mock_build_model, mock_next_step, mock_save
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
    def test_answer_is_persisted_even_if_the_llm_call_then_fails(
        self, mock_load, mock_require, mock_build_model, mock_next_step
    ):
        """Antes, si next_step fallaba, la respuesta recien dada se perdia:
        la funcion salia por el except sin llamar a save_session_state, asi
        que la respuesta del usuario (ya aceptada por el endpoint) nunca
        quedaba en el historial. Al recargar, GET /elicitation devolvia otra
        vez la pregunta vieja como si no se hubiera contestado."""
        mock_require.return_value = make_project()
        mock_load.return_value = {
            "engram_state": {"1": {"requerimientos": {
                "preguntas_respuestas": [],
                "pending_question": "¿cual es el presupuesto?",
                "resumen": None,
            }}}
        }
        mock_build_model.return_value = MagicMock()
        mock_next_step.side_effect = elicitation_agent.ElicitationAgentError("JSON invalido")

        saved_state = {}

        def fake_save(user_id, project_id, active_phase, engram_state):
            saved_state.update(engram_state)

        with patch("app.api.elicitation.save_session_state", side_effect=fake_save):
            with pytest.raises(HTTPException) as exc_info:
                run(send_elicitation_message(
                    project_id=1,
                    body=ElicitationMessageIn(answer="el presupuesto subio a 13000 dolares"),
                    current_user=CURRENT_USER,
                ))

        assert exc_info.value.status_code == 502
        # La respuesta quedo guardada aunque la llamada al LLM haya fallado.
        phase = saved_state["1"]["requerimientos"]
        assert phase["preguntas_respuestas"] == [
            {"pregunta": "¿cual es el presupuesto?", "respuesta": "el presupuesto subio a 13000 dolares"}
        ]
        # Sin pregunta pendiente ni resumen: el reintento automatico del
        # frontend (ChatWindow: "if (!state.done && !state.question)")
        # dispara otro POST sin "answer" para generar la siguiente pregunta
        # con este mismo historial, sin que el usuario reescriba nada.
        assert phase["pending_question"] is None
        assert phase["resumen"] is None

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
