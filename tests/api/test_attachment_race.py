"""Regression test for the F13 attachment persistence race (PR #104, review #4).

The agent emits an ``event: attachment`` SSE payload as soon as the
``puppeteer_screenshot`` tool returns. The frontend renders the inline
PNG (``<img src=...>``) on receipt of that event, which fires the GET
/api/chat/attachments/{id}?token=... request to the backend.

The chat route persists the assistant message + attachments inside
``_persist_turn``, which runs on ``event: done`` — AFTER every
``event: attachment`` has already been emitted. In production a browser
that fires the ``<img>`` request immediately after receiving
``event: attachment`` can race ahead of ``_persist_turn`` and get a
404 from the attachments route. The exact window depends on the SSE
buffering of the upstream proxy (uvicorn, nginx, Cloudflare); this
test pins the BEHAVIOUR the route must guarantee — the assistant row
must be queryable from a separate session once ``event: attachment``
has been emitted, so the first ``<img>`` request resolves.

This is a NO-FIX with documented residual risk: the production code
keeps the atomic REQ-ATT-1 transaction (``_persist_turn`` on
``event: done``) so a partial failure cannot leave an attachment row
without its assistant message, at the cost of a small race window.
Closing the race fully would require persisting each attachment in
its own transaction as it arrives, which relaxes the atomicity
guarantee REQ-ATT-1. That trade-off belongs in a separate PR, not
in PR #104.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

from app.api.chat import router as chat_router
from app.core import attachment_tokens
from app.core import database
from app.core.database import Base
from sqlalchemy.dialects import sqlite as _sqlite_dialect  # noqa: E402

if not hasattr(_sqlite_dialect.dialect, "_f13_race_patched"):
    _sqlite_dialect.dialect.ischema_names = {
        **_sqlite_dialect.dialect.ischema_names,
        "JSONB": JSON,
    }
    _sqlite_dialect.dialect._f13_race_patched = True


_TEST_TABLES = ["users", "sessions", "projects", "messages"]


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-race")


@pytest.fixture()
def fake_db():
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

    with patch("app.api.chat.SessionLocal", Session), \
         patch("app.api.attachments.SessionLocal", Session):
        yield Session, engine

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


def _build_chat_client(user_id: int = 1) -> TestClient:
    """Build a TestClient for the chat route with auth overridden."""
    from app.api.dependencies import get_current_user

    app = FastAPI()
    app.include_router(chat_router)

    async def fake_current_user():
        return {"user_id": user_id, "username": "alice"}

    app.dependency_overrides[get_current_user] = fake_current_user
    return TestClient(app)


def _build_attachment_client(user_id: int = 1) -> TestClient:
    """Build a TestClient for the attachments route with auth overridden."""
    from app.api import attachments as attachments_module

    app = FastAPI()
    app.include_router(attachments_module.router)

    def _fake_get_current_user():
        return user_id

    app.dependency_overrides[attachments_module.get_current_user] = _fake_get_current_user
    return TestClient(app)


def _attachment_event_payload(*, attachment_id: str, storage_path: str) -> dict:
    """Build the full server-side attachment dict (the agent's view)."""
    return {
        "id": attachment_id,
        "kind": "screenshot",
        "mime": "image/png",
        "filename": f"{attachment_id}.png",
        "storage_path": storage_path,
        "source_url": "data:image/png;base64,ZmFrZQ==",
        "bytes": 4,
    }


def test_attachment_row_queryable_between_attachment_and_done(
    fake_db, tmp_path, monkeypatch
):
    """RED → GREEN: after the SSE stream yields ``event: attachment``
    but BEFORE it yields ``event: done``, the messages row carrying the
    attachment must already be queryable from a SEPARATE database
    session — so the browser's first ``<img>`` request (which lands in
    exactly that window) can resolve the attachment id.

    The chat route used to buffer attachments and only flush them inside
    ``_persist_turn`` on ``event: done``. After the fix each
    ``event: attachment`` payload commits the assistant row immediately
    (atomicity relaxed — see PR #104 review note in the patch).
    """
    from app.api import chat as chat_module

    png_path = tmp_path / "race.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    attachment_id = "att-race-1"
    payload = _attachment_event_payload(
        attachment_id=attachment_id, storage_path=str(png_path)
    )

    async def fake_run_agent(*_args, **_kwargs):
        # Inject a small delay between the two yields so the test thread
        # has a real window to query the DB after ``event: attachment``
        # but before ``_persist_turn`` fires.
        import asyncio

        yield {"event": "attachment", "data": payload}
        await asyncio.sleep(0.05)
        yield {"event": "done", "data": None}

    fake_model = MagicMock(name="fake-model")
    fake_model.model_name = "fake-model"

    _seed(fake_db)
    client = _build_chat_client(user_id=1)

    with patch.object(chat_module, "run_agent", side_effect=fake_run_agent), \
         patch.object(chat_module, "build_langchain_model", return_value=fake_model), \
         patch.object(
             chat_module,
             "similarity_search",
             return_value=([], {"embedding_ms": 0, "search_ms": 0, "total_ms": 0}),
         ), \
         patch.object(chat_module, "get_langfuse_handler", return_value=None):
        # Stream the chat response so we can observe each event as it
        # arrives. We use ``client.stream`` + a manual read loop so the
        # thread interleaves with the in-flight ``_persist_turn``.
        with client.stream("POST", "/api/chat", json={"project_id": 1, "message": "draw me something"}) as r:
            assert r.status_code == 200
            chunks: list[str] = []
            saw_done = False
            saw_attachment = False
            saw_attachment_at: int | None = None

            for chunk in r.iter_text():
                if not chunk:
                    continue
                chunks.append(chunk)
                # After we see ``event: attachment`` in the raw stream,
                # IMMEDIATELY query the DB from a separate session — this
                # is exactly what the browser's first ``<img>`` request
                # would do.
                if "event: attachment" in chunk and not saw_attachment:
                    saw_attachment = True
                    Session, _engine = fake_db
                    with Session() as probe:
                        from app.models.message import Message

                        rows = (
                            probe.query(Message)
                            .filter(Message.user_id == 1, Message.role == "assistant")
                            .all()
                        )
                    # Pin: by the time ``event: attachment`` is on the
                    # wire, at least one assistant row exists in the DB
                    # AND it carries the attachment id the browser will
                    # request next. The previous implementation left the
                    # row absent here, returning 404 for the inline
                    # ``<img>``.
                    assert rows, (
                        "No assistant row persisted when 'event: attachment' "
                        "was emitted; the browser's <img> request would 404."
                    )
                    ids: list[str] = []
                    for row in rows:
                        for att in (row.attachments or []):
                            if isinstance(att, dict):
                                ids.append(att.get("id"))
                    assert attachment_id in ids, (
                        f"Attachment {attachment_id!r} not persisted before "
                        f"'event: done'; found ids={ids}."
                    )

                if "event: done" in chunk and not saw_done:
                    saw_done = True

            assert saw_attachment, "test driver never saw 'event: attachment'"
            assert saw_done, "test driver never saw 'event: done'"