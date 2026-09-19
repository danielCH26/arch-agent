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

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import database
from app.core.database import Base

PHASE = "requerimientos"  # AVAILABLE_PHASES[0] en app/api/projects.py

_TEST_TABLES = ["users", "sessions", "projects", "approvals"]


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
