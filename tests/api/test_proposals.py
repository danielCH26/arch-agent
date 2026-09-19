"""Contract tests para POST /api/projects/{id}/proposal/decision y
GET /api/projects/{id}/proposal (hallazgo #7, revisión
feature/hu6-diagrama): no había tests para el camino de `decide_proposal`
sin una `UserSession` previa -- justo el que documenta el docstring de
`record_approval_decision` (la crea de forma perezosa en vez de tirar 400).

Mismo patrón que tests/api/test_chat_history.py / tests/api/test_diagrams.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

from app.core import database
from app.core.database import Base


from sqlalchemy.dialects import sqlite as _sqlite_dialect  # noqa: E402

if not hasattr(_sqlite_dialect.dialect, "_proposals_jsonb_patched"):
    _sqlite_dialect.dialect.ischema_names = {
        **_sqlite_dialect.dialect.ischema_names,
        "JSONB": JSON,
    }
    _sqlite_dialect.dialect._proposals_jsonb_patched = True


_TEST_TABLES = ["users", "sessions", "projects", "messages", "approvals"]


@pytest.fixture()
def fake_db():
    """Spin up an in-memory SQLite + patch SessionLocal.

    `decide_proposal`/`get_proposal_state` usan `app.api.proposals.
    SessionLocal` directamente, pero `_require_project` (llamado antes,
    para validar ownership) hace su propio `from app.core.database import
    SessionLocal` DENTRO de la función -- lee el atributo del módulo en
    cada llamada, así que también hay que parchear `database.SessionLocal`.
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

    with patch("app.api.proposals.SessionLocal", Session), \
         patch("app.core.database.SessionLocal", Session):
        yield Session, engine

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


def _insert_assistant_message(
    fake_db, *, session_id: int, user_id: int, project_id: int, content: str,
    created_at: datetime,
):
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.message import Message

        db.add(
            Message(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                role="assistant",
                content=content,
                citations=[],
                created_at=created_at,
                updated_at=created_at,
            )
        )
        db.commit()
    finally:
        db.close()


def _client_for_user(user_id: int = 1, username: str = "alice"):
    from fastapi import FastAPI
    from app.api.proposals import router as proposals_router

    app = FastAPI()
    app.include_router(proposals_router)

    async def fake_current_user():
        return {"user_id": user_id, "username": username}

    deps = __import__("app.api.dependencies", fromlist=["get_current_user"])
    app.dependency_overrides = {deps.get_current_user: fake_current_user}
    return TestClient(app)


def _has_user_session(fake_db, user_id: int) -> bool:
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.session import UserSession

        return db.query(UserSession).filter(UserSession.user_id == user_id).first() is not None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/projects/{id}/proposal/decision — camino SIN UserSession previa
# ---------------------------------------------------------------------------


class TestDecideProposalWithoutExistingSession:
    def test_approve_with_explicit_proposal_text_creates_session_lazily(self, fake_db):
        """El usuario puede llegar directo desde el chat, sin haber pasado
        nunca por /elicitation -- no debe bloquearse por falta de una fila
        de bookkeeping."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        assert _has_user_session(fake_db, 1) is False

        client = _client_for_user(user_id=1)
        response = client.post(
            "/api/projects/1/proposal/decision",
            json={"decision": "approve", "proposal_text": "Arquitectura hexagonal con 3 capas."},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "approve"
        assert body["phase_ready"] is True
        assert body["proposal_snapshot_chars"] == len("Arquitectura hexagonal con 3 capas.")
        assert _has_user_session(fake_db, 1) is True

    def test_approve_without_session_cannot_use_chat_history_fallback(self, fake_db):
        """El fallback a \"último mensaje del asistente\" necesita
        `session_row.id` para buscar el historial -- sin una UserSession
        previa, ese fallback ni se intenta, aunque haya mensajes del
        asistente en la base. Solo `proposal_text` explícito sirve en ese
        caso (ver `test_approve_with_explicit_proposal_text_creates_
        session_lazily`)."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _insert_assistant_message(
            fake_db, session_id=999, user_id=1, project_id=1,
            content="Propuesta: microservicios con API Gateway.",
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        client = _client_for_user(user_id=1)
        response = client.post(
            "/api/projects/1/proposal/decision", json={"decision": "approve"}
        )

        assert response.status_code == 400

    def test_approve_with_session_falls_back_to_latest_assistant_message(self, fake_db):
        """Con una UserSession ya existente (p. ej. porque el usuario ya
        pasó por /elicitation), sin `proposal_text` explícito sí cae al
        fallback de \"último mensaje del asistente de este proyecto\"."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.session import UserSession

            db.add(UserSession(id=999, user_id=1))
            db.commit()
        finally:
            db.close()
        _insert_assistant_message(
            fake_db, session_id=999, user_id=1, project_id=1,
            content="Propuesta: microservicios con API Gateway.",
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        client = _client_for_user(user_id=1)
        response = client.post(
            "/api/projects/1/proposal/decision", json={"decision": "approve"}
        )

        assert response.status_code == 200
        assert response.json()["proposal_snapshot_chars"] == len(
            "Propuesta: microservicios con API Gateway."
        )

    def test_approve_without_session_and_without_any_proposal_returns_400(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/proposal/decision", json={"decision": "approve"}
        )

        assert response.status_code == 400
        # Sin propuesta que aprobar, no debe crearse ninguna Approval ni
        # UserSession -- la validación corre ANTES de registrar la decisión.
        assert _has_user_session(fake_db, 1) is False

    def test_modify_without_session_requires_feedback(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/proposal/decision", json={"decision": "modify"}
        )

        assert response.status_code == 400

    def test_reject_without_session_still_persists_decision(self, fake_db):
        """`reject` no necesita snapshot ni feedback -- debe funcionar
        igual sin UserSession previa."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/projects/1/proposal/decision", json={"decision": "reject"}
        )

        assert response.status_code == 200
        assert response.json()["phase_ready"] is False
        assert _has_user_session(fake_db, 1) is True


# ---------------------------------------------------------------------------
# GET /api/projects/{id}/proposal — hallazgo #1 (aislamiento entre proyectos)
# ---------------------------------------------------------------------------


class TestGetProposalState:
    def test_returns_not_approved_when_no_user_session_exists(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.get("/api/projects/1/proposal")

        assert response.status_code == 200
        assert response.json() == {
            "approved": False,
            "approved_at": None,
            "approval_id": None,
            "proposal_snapshot_chars": 0,
            "last_decision": None,
        }

    def test_approving_project_a_does_not_leak_into_project_b(self, fake_db):
        """Hallazgo #1: `sessions` es una fila por usuario, no por
        proyecto -- aprobar la propuesta del proyecto A no debe hacer que
        GET /proposal del proyecto B (nunca aprobado) devuelva
        approved=True."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1, project_name="A")
        _seed_user_and_project(fake_db, user_id=1, project_id=2, project_name="B")
        client = _client_for_user(user_id=1)

        approve = client.post(
            "/api/projects/1/proposal/decision",
            json={"decision": "approve", "proposal_text": "Propuesta del proyecto A"},
        )
        assert approve.status_code == 200

        state_a = client.get("/api/projects/1/proposal")
        state_b = client.get("/api/projects/2/proposal")

        assert state_a.json()["approved"] is True
        assert state_b.json()["approved"] is False
        assert state_b.json()["proposal_snapshot_chars"] == 0

    def test_modify_after_approve_clears_snapshot_and_phase_ready(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        client.post(
            "/api/projects/1/proposal/decision",
            json={"decision": "approve", "proposal_text": "v1 de la propuesta"},
        )
        modify = client.post(
            "/api/projects/1/proposal/decision",
            json={"decision": "modify", "feedback": "cambiá el storage a S3"},
        )

        assert modify.status_code == 200
        assert modify.json()["phase_ready"] is False

        state = client.get("/api/projects/1/proposal")
        assert state.json()["approved"] is False
        assert state.json()["proposal_snapshot_chars"] == 0
        assert state.json()["last_decision"] == "modified"

    def test_404_for_cross_user_project(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=2, project_id=2, project_name="P2")
        client = _client_for_user(user_id=1)

        response = client.get("/api/projects/2/proposal")

        assert response.status_code in (403, 404)
