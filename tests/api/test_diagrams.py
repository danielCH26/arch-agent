"""Contract tests para /api/diagrams (hallazgo #7, revisión
feature/hu6-diagrama): no había ningún test para GET /api/diagrams/history
ni para POST /api/diagrams/decision, así que los bugs de los hallazgos #1
(aislamiento entre proyectos) y #10 (historial sin límite) los habría
atrapado CI.

Mismo patrón que tests/api/test_chat_history.py: SQLite in-memory +
monkey-patch de ``SessionLocal`` en el módulo de la ruta bajo prueba.
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


# JSONB → JSON so SQLite can compile the messages/approvals tables.
from sqlalchemy.dialects import sqlite as _sqlite_dialect  # noqa: E402

if not hasattr(_sqlite_dialect.dialect, "_diagrams_jsonb_patched"):
    _sqlite_dialect.dialect.ischema_names = {
        **_sqlite_dialect.dialect.ischema_names,
        "JSONB": JSON,
    }
    _sqlite_dialect.dialect._diagrams_jsonb_patched = True


_TEST_TABLES = ["users", "sessions", "projects", "messages", "approvals"]


@pytest.fixture()
def fake_db():
    """Spin up an in-memory SQLite + patch SessionLocal en app.api.diagrams.

    Los helpers de ``record_approval_decision``/``ensure_user_session``
    reciben la misma sesión que la ruta abre (no abren la suya propia), así
    que basta con patchear el ``SessionLocal`` del módulo de la ruta.
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

    with patch("app.api.diagrams.SessionLocal", Session):
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
    fake_db,
    *,
    session_id: int,
    user_id: int,
    project_id: int,
    attachments: list[dict] | None,
    created_at: datetime,
):
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.session import UserSession
        from app.models.message import Message

        if db.query(UserSession).filter(UserSession.user_id == user_id).first() is None:
            db.add(UserSession(id=session_id, user_id=user_id))
            db.commit()

        db.add(
            Message(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                role="assistant",
                content="aca va el diagrama",
                citations=[],
                attachments=attachments or [],
                created_at=created_at,
                updated_at=created_at,
            )
        )
        db.commit()
    finally:
        db.close()


def _client_for_user(user_id: int = 1, username: str = "alice"):
    from fastapi import FastAPI
    from app.api.diagrams import router as diagrams_router

    app = FastAPI()
    app.include_router(diagrams_router)

    async def fake_current_user():
        return {"user_id": user_id, "username": username}

    deps = __import__("app.api.dependencies", fromlist=["get_current_user"])
    app.dependency_overrides = {deps.get_current_user: fake_current_user}
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/diagrams/history
# ---------------------------------------------------------------------------


class TestDiagramHistory:
    def test_returns_screenshot_attachments_newest_first(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[{"id": "att-1", "kind": "screenshot", "filename": "d1.png"}],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[{"id": "att-2", "kind": "screenshot", "filename": "d2.png"}],
            created_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=1")

        assert response.status_code == 200
        diagrams = response.json()["diagrams"]
        assert [d["message_id"] for d in diagrams] == sorted(
            [d["message_id"] for d in diagrams], reverse=True
        )
        assert [d["filename"] for d in diagrams] == ["d2.png", "d1.png"]

    def test_re_signs_url_at_response_time_instead_of_reusing_stale_token(self, fake_db):
        """Bug fix (HU6): el token guardado en `attachments[].url` tiene TTL
        de 5 min. El endpoint debe re-firmar con build_attachment_url en vez
        de servir la URL vieja tal cual."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[{
                "id": "att-1", "kind": "screenshot", "filename": "d1.png",
                "url": "/api/chat/attachments/att-1?token=YA-VENCIDO",
            }],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=1")

        assert response.status_code == 200
        url = response.json()["diagrams"][0]["url"]
        assert "YA-VENCIDO" not in url
        assert url.startswith("/api/chat/attachments/att-1?token=")

    def test_ignores_non_screenshot_attachments(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[{"id": "att-1", "kind": "document", "filename": "notas.pdf"}],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=1")

        assert response.status_code == 200
        assert response.json() == {"diagrams": []}

    def test_ignores_messages_without_attachments(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=1")

        assert response.status_code == 200
        assert response.json() == {"diagrams": []}

    def test_404_for_unknown_project(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=999")

        assert response.status_code == 404

    def test_404_for_cross_user_project(self, fake_db):
        """Hallazgo #1 (aislamiento entre proyectos): un diagrama del
        proyecto de otro usuario nunca debe aparecer, ni siquiera como 404
        \"silencioso\" que filtre existencia."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=2, project_id=2, project_name="P2")
        _insert_assistant_message(
            fake_db, session_id=20, user_id=2, project_id=2,
            attachments=[{"id": "att-1", "kind": "screenshot", "filename": "d1.png"}],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=2")

        assert response.status_code == 404

    def test_does_not_leak_other_project_diagrams_of_same_user(self, fake_db):
        """Hallazgo #1: dos proyectos del MISMO usuario no deben mezclar
        diagramas entre sí."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1, project_name="A")
        _seed_user_and_project(fake_db, user_id=1, project_id=2, project_name="B")
        _insert_assistant_message(
            fake_db, session_id=10, user_id=1, project_id=1,
            attachments=[{"id": "att-a", "kind": "screenshot", "filename": "da.png"}],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        client = _client_for_user(user_id=1)

        response = client.get("/api/diagrams/history?project_id=2")

        assert response.status_code == 200
        assert response.json() == {"diagrams": []}


# ---------------------------------------------------------------------------
# POST /api/diagrams/decision
# ---------------------------------------------------------------------------


class TestDecideDiagram:
    def test_approve_persists_approval_row(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1", json={"decision": "approve"}
        )

        assert response.status_code == 200
        assert response.json() == {"decision": "approve", "message": "Diagrama aprobado."}

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.approval import Approval

            rows = db.query(Approval).filter(Approval.phase == "diagram").all()
            assert len(rows) == 1
            assert rows[0].decision == "approved"
            assert rows[0].project_id == 1
        finally:
            db.close()

    def test_does_not_require_a_pre_existing_user_session(self, fake_db):
        """Antes tiraba 400 si no habia una `UserSession` todavia; ahora
        `record_approval_decision` la crea de forma perezosa (mismo
        criterio que /proposal/decision) -- un usuario puede aprobar el
        diagrama sin haber pasado antes por /elicitation."""
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
            "/api/diagrams/decision?project_id=1", json={"decision": "approve"}
        )

        assert response.status_code == 200
        db = Session()
        try:
            from app.models.session import UserSession

            assert db.query(UserSession).filter(UserSession.user_id == 1).first() is not None
        finally:
            db.close()

    def test_modify_requires_feedback(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1", json={"decision": "modify"}
        )

        assert response.status_code == 400

    def test_modify_with_feedback_persists_it(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": "modify", "feedback": "cambiá el color del nodo A"},
        )

        assert response.status_code == 200
        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.approval import Approval

            row = db.query(Approval).filter(Approval.phase == "diagram").first()
            assert row.decision == "modified"
            assert row.feedback == "cambiá el color del nodo A"
        finally:
            db.close()

    def test_reject_does_not_require_feedback(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1", json={"decision": "reject"}
        )

        assert response.status_code == 200
        assert response.json()["decision"] == "reject"

    def test_404_for_unknown_project(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=999", json={"decision": "approve"}
        )

        assert response.status_code == 404

    def test_404_for_cross_user_project(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=2, project_id=2, project_name="P2")
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=2", json={"decision": "approve"}
        )

        assert response.status_code == 404

    def test_approve_on_one_project_does_not_leak_into_another(self, fake_db):
        """Hallazgo #1: aprobar el diagrama del proyecto A no debe hacer
        que la fila quede asociada (o visible) para el proyecto B del
        mismo usuario."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1, project_name="A")
        _seed_user_and_project(fake_db, user_id=1, project_id=2, project_name="B")
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1", json={"decision": "approve"}
        )
        assert response.status_code == 200

        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.approval import Approval

            rows = db.query(Approval).filter(Approval.phase == "diagram").all()
            assert len(rows) == 1
            assert rows[0].project_id == 1
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Decisión POR diagrama (migración 0017: approvals.attachment_id)
#
# Bug QA HU6: rechazar un diagrama en el chat no se recordaba -- tras un F5
# volvían los tres botones -- y el panel de historial dejaba decidir otra vez
# sobre un diagrama ya decidido. La decisión ahora se guarda por diagrama y se
# devuelve en el historial.
# ---------------------------------------------------------------------------


def _seed_diagram(fake_db, *, user_id=1, project_id=1, attachment_id="att-1", minute=0):
    _insert_assistant_message(
        fake_db, session_id=10, user_id=user_id, project_id=project_id,
        attachments=[{"id": attachment_id, "kind": "screenshot", "filename": f"{attachment_id}.png"}],
        created_at=datetime(2024, 1, 1, 12, minute, 0, tzinfo=timezone.utc),
    )


def _approval_rows(fake_db):
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.approval import Approval

        return [
            (r.attachment_id, r.decision, r.project_id)
            for r in db.query(Approval).filter(Approval.phase == "diagram").order_by(Approval.id).all()
        ]
    finally:
        db.close()


class TestPerDiagramDecision:
    def test_history_exposes_attachment_id_and_no_decision_by_default(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_diagram(fake_db, attachment_id="att-1")
        client = _client_for_user(user_id=1)

        diagrams = client.get("/api/diagrams/history?project_id=1").json()["diagrams"]

        assert diagrams[0]["id"] == "att-1"
        assert diagrams[0]["decision"] is None

    @pytest.mark.parametrize("decision", ["approve", "reject", "modify"])
    def test_decision_is_persisted_per_diagram_and_returned_by_history(self, fake_db, decision):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_diagram(fake_db, attachment_id="att-1")
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": decision, "feedback": "cambia algo", "attachment_id": "att-1"},
        )

        assert response.status_code == 200
        assert _approval_rows(fake_db) == [("att-1", {"approve": "approved", "reject": "rejected", "modify": "modified"}[decision], 1)]
        diagrams = client.get("/api/diagrams/history?project_id=1").json()["diagrams"]
        assert diagrams[0]["decision"] == decision

    def test_deciding_one_diagram_does_not_mark_the_others(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_diagram(fake_db, attachment_id="att-1", minute=0)
        _seed_diagram(fake_db, attachment_id="att-2", minute=5)
        client = _client_for_user(user_id=1)

        client.post("/api/diagrams/decision?project_id=1", json={"decision": "reject", "attachment_id": "att-2"})

        by_id = {d["id"]: d["decision"] for d in client.get("/api/diagrams/history?project_id=1").json()["diagrams"]}
        assert by_id == {"att-1": None, "att-2": "reject"}

    def test_second_decision_on_same_diagram_is_409_and_not_persisted(self, fake_db):
        """Ya aprobado / rechazado / con cambios pedidos: no se puede decidir
        de nuevo (p. ej. desde otra pestaña o llamando a la API directo)."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_diagram(fake_db, attachment_id="att-1")
        client = _client_for_user(user_id=1)
        body = {"decision": "approve", "attachment_id": "att-1"}
        assert client.post("/api/diagrams/decision?project_id=1", json=body).status_code == 200

        again = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": "reject", "attachment_id": "att-1"},
        )

        assert again.status_code == 409
        assert "ya tiene una decisión" in again.json()["detail"]
        assert _approval_rows(fake_db) == [("att-1", "approved", 1)]

    def test_404_for_unknown_attachment_id(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": "approve", "attachment_id": "no-existe"},
        )

        assert response.status_code == 404
        assert _approval_rows(fake_db) == []

    def test_404_when_attachment_belongs_to_another_project_of_same_user(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=1, project_id=2)
        _seed_diagram(fake_db, project_id=2, attachment_id="att-de-otro-proyecto")
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": "approve", "attachment_id": "att-de-otro-proyecto"},
        )

        assert response.status_code == 404

    def test_404_when_attachment_belongs_to_another_user(self, fake_db):
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        _seed_user_and_project(fake_db, user_id=2, project_id=2)
        _seed_diagram(fake_db, user_id=2, project_id=2, attachment_id="att-ajeno")
        client = _client_for_user(user_id=1)

        response = client.post(
            "/api/diagrams/decision?project_id=1",
            json={"decision": "approve", "attachment_id": "att-ajeno"},
        )

        assert response.status_code == 404

    def test_decision_without_attachment_id_still_works_as_before(self, fake_db):
        """Compatibilidad: un cliente viejo sin `attachment_id` sigue
        registrando la decisión a nivel de proyecto."""
        _seed_user_and_project(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        response = client.post("/api/diagrams/decision?project_id=1", json={"decision": "approve"})

        assert response.status_code == 200
        assert _approval_rows(fake_db) == [(None, "approved", 1)]
