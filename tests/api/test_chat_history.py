"""Contract tests for GET /api/chat/history (F12.2, REQ-7, REQ-11, SCN-3, SCN-5).

The endpoint is exercised through FastAPI's TestClient. To stay DB-agnostic
we monkey-patch ``SessionLocal`` to return a session bound to an in-memory
SQLite engine, the same way the production code uses ``SessionLocal`` from
``app.core.database``. We also monkey-patch ``app.core.database.engine`` /
``SessionLocal`` so the chat route picks up our fake.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

from app.core import database
from app.core.database import Base


# JSONB → JSON so SQLite can compile the messages table.
from sqlalchemy.dialects import sqlite as _sqlite_dialect  # noqa: E402

if not hasattr(_sqlite_dialect.dialect, "_f12_jsonb_patched"):
    _sqlite_dialect.dialect.ischema_names = {
        **_sqlite_dialect.dialect.ischema_names,
        "JSONB": JSON,
    }
    _sqlite_dialect.dialect._f12_jsonb_patched = True


_TEST_TABLES = ["users", "sessions", "projects", "messages"]


@pytest.fixture()
def fake_db():
    """Spin up an in-memory SQLite + patch the production SessionLocal.

    We use ``StaticPool`` so every session shares the SAME connection —
    otherwise each new connection to ``sqlite:///:memory:`` would open
    a separate database and the test would not see the seeded rows.

    Yields a ``(SessionLocal, engine)`` tuple so the test can seed rows.
    The patch is undone automatically at teardown.
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

    # Patch the symbols imported by app.api.chat.
    with patch("app.api.chat.SessionLocal", Session):
        yield Session, engine

    # Restore so subsequent modules see the real engine again.
    database.SessionLocal = real_session_local
    engine.dispose()


def _seed(fake_db, *, user_id: int = 1, project_id: int = 1, session_id: int = 10):
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.user import User
        from app.models.session import UserSession
        from app.models.project import Project

        db.add(User(id=user_id, username=f"u{user_id}", email=f"u{user_id}@x", password_hash="x"))
        db.add(Project(id=project_id, user_id=user_id, name="P"))
        db.add(UserSession(id=session_id, user_id=user_id))
        db.commit()
    finally:
        db.close()


def _insert_messages(fake_db, session_id: int, user_id: int, project_id: int, items):
    """Insert N Message rows with deterministic created_at (oldest first)."""
    Session, _engine = fake_db
    db = Session()
    try:
        from app.models.message import Message

        for idx, content in enumerate(items):
            db.add(
                Message(
                    session_id=session_id,
                    project_id=project_id,
                    user_id=user_id,
                    role="user" if idx % 2 == 0 else "assistant",
                    content=content,
                    citations=[],
                    created_at=datetime(2024, 1, 1, 12, 0, idx, tzinfo=timezone.utc),
                    updated_at=datetime(2024, 1, 1, 12, 0, idx, tzinfo=timezone.utc),
                )
            )
        db.commit()
    finally:
        db.close()


def _client_for_user(user_id: int = 1, username: str = "alice"):
    """Build a FastAPI TestClient with get_current_user stubbed."""
    from fastapi import FastAPI
    from app.api.chat import router as chat_router

    app = FastAPI()
    app.include_router(chat_router)

    async def fake_current_user():
        return {"user_id": user_id, "username": username}

    app.dependency_overrides = {
        # import lazily to avoid pulling FastAPI machinery at module import
        __import__("app.api.dependencies", fromlist=["get_current_user"]).get_current_user: fake_current_user
    }
    return TestClient(app)


class TestChatHistoryEndpoint:
    def test_returns_last_n_messages_newest_first(self, fake_db):
        _seed(fake_db)
        _insert_messages(fake_db, session_id=10, user_id=1, project_id=1, items=[
            "u1", "a1", "u2", "a2", "u3", "a3", "u4", "a4",
        ])
        client = _client_for_user(user_id=1)

        response = client.get("/api/chat/history?project_id=1&limit=5")

        assert response.status_code == 200
        body = response.json()
        messages = body["messages"]
        assert len(messages) == 5
        # Newest first → last 5 inserted (a4, u4, a3, u3, a2)
        assert [m["content"] for m in messages] == ["a4", "u4", "a3", "u3", "a2"]
        assert all(m["role"] in {"user", "assistant", "system"} for m in messages)
        assert all("created_at" in m for m in messages)
        assert all(m["citations"] == [] for m in messages)

    def test_default_limit_is_5(self, fake_db):
        _seed(fake_db)
        _insert_messages(fake_db, 10, 1, 1, [f"m{i}" for i in range(20)])
        client = _client_for_user(user_id=1)

        response = client.get("/api/chat/history?project_id=1")

        assert response.status_code == 200
        assert len(response.json()["messages"]) == 5

    def test_limit_clamped_to_max_50(self, fake_db):
        _seed(fake_db)
        client = _client_for_user(user_id=1)

        # FastAPI Query(le=50) → 422 on out-of-range.
        response = client.get("/api/chat/history?project_id=1&limit=100")
        assert response.status_code == 422

    def test_limit_clamped_to_min_1(self, fake_db):
        _seed(fake_db)
        client = _client_for_user(user_id=1)

        response = client.get("/api/chat/history?project_id=1&limit=0")
        assert response.status_code == 422

    def test_404_for_unknown_project(self, fake_db):
        _seed(fake_db)
        client = _client_for_user(user_id=1)

        response = client.get("/api/chat/history?project_id=999")
        assert response.status_code == 404

    def test_404_for_cross_user_project(self, fake_db):
        """Cross-user access must NOT leak existence — REQ-7."""
        _seed(fake_db, user_id=1, project_id=1)
        client = _client_for_user(user_id=1)

        # user 2 has a separate project — ask for it as user 1
        response = client.get("/api/chat/history?project_id=2")
        assert response.status_code == 404

    def test_returns_empty_list_when_user_has_no_session(self, fake_db):
        """Fresh user (with a project) but no UserSession row still gets []."""
        Session, _engine = fake_db
        db = Session()
        try:
            from app.models.user import User
            from app.models.project import Project

            db.add(User(id=2, username="u2", email="u2@x", password_hash="x"))
            db.add(Project(id=1, user_id=2, name="P2"))
            db.commit()
        finally:
            db.close()

        client = _client_for_user(user_id=2)
        response = client.get("/api/chat/history?project_id=1&limit=5")
        assert response.status_code == 200
        assert response.json() == {"messages": []}

    def test_postgres_down_returns_200_empty(self, fake_db):
        """REQ-11 / SCN-5: when the message SELECT raises, endpoint returns 200 []."""
        from fastapi import FastAPI
        from app.api.chat import router as chat_router
        from app.models.project import Project

        _seed(fake_db)
        client = _client_for_user(user_id=1)

        # Wrap SessionLocal so the project query succeeds but the message
        # SELECT raises OperationalError. This mirrors a connection that
        # drops between the ownership check and the message fetch.
        from sqlalchemy.exc import OperationalError
        from unittest.mock import patch

        Session, _engine = fake_db

        class BrokenMessagesSession:
            def __init__(self):
                self._delegate = Session()

            def query(self, model):
                # Project query works; any other query (UserSession or
                # Message via list_recent) raises.
                if model is Project:
                    return self._delegate.query(model)
                raise OperationalError("SELECT 1", {}, Exception("connection refused"))

            def close(self):
                self._delegate.close()

        app = FastAPI()
        app.include_router(chat_router)

        async def fake_current_user():
            return {"user_id": 1, "username": "alice"}

        deps = __import__("app.api.dependencies", fromlist=["get_current_user"])
        app.dependency_overrides[deps.get_current_user] = fake_current_user

        with patch("app.api.chat.SessionLocal", BrokenMessagesSession):
            response = client.get("/api/chat/history?project_id=1&limit=5")
        assert response.status_code == 200
        assert response.json() == {"messages": []}

    def test_message_shape_includes_required_fields(self, fake_db):
        _seed(fake_db)
        _insert_messages(fake_db, 10, 1, 1, ["hola"])
        client = _client_for_user(user_id=1)

        response = client.get("/api/chat/history?project_id=1&limit=5")
        assert response.status_code == 200
        msg = response.json()["messages"][0]
        assert set(msg.keys()) == {"id", "role", "content", "citations", "created_at"}
