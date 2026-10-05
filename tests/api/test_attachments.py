"""
Tests for ``GET /api/chat/attachments/{id}`` (F13, REQ-ATT-2 / REQ-ATT-3,
SCN-ATT-3..6).

Mirrors the conventions of ``tests/api/test_chat_history.py``: in-memory
SQLite + patched ``SessionLocal`` so the test never touches a real
Postgres. Coverage:
  - 200 happy path: Content-Type from row + Content-Disposition inline
  - 401 missing token, 401 expired, 401 forged, 401 cross-id
  - 404 cross-user (NOT 403 — avoid existence leak)
  - 404 unknown id
  - No WARNING log on 404 (info-leak posture)
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

from app.core import database
from app.core.database import Base
from app.core import attachment_tokens


# JSONB → JSON so SQLite can compile the messages table.
from sqlalchemy.dialects import sqlite as _sqlite_dialect  # noqa: E402

if not hasattr(_sqlite_dialect.dialect, "_f13_jsonb_patched"):
    _sqlite_dialect.dialect.ischema_names = {
        **_sqlite_dialect.dialect.ischema_names,
        "JSONB": JSON,
    }
    _sqlite_dialect.dialect._f13_jsonb_patched = True


_TEST_TABLES = ["users", "sessions", "projects", "messages"]


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-for-attachments")


@pytest.fixture()
def fake_db():
    """Spin up an in-memory SQLite + patch the production SessionLocal."""
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

    with patch("app.api.attachments.SessionLocal", Session):
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


def _insert_message_with_attachment(
    fake_db,
    *,
    user_id: int,
    project_id: int,
    session_id: int,
    attachments: list[dict],
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
                content="here's the diagram",
                citations=[],
                attachments=attachments,
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()
    finally:
        db.close()


def _client():
    from app.api.attachments import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestAttachmentEndpoint:
    def test_401_missing_token(self, fake_db):
        client = _client()
        response = client.get("/api/chat/attachments/att-xyz")
        assert response.status_code == 401

    def test_401_forged_token(self, fake_db):
        client = _client()
        response = client.get(
            "/api/chat/attachments/att-xyz?token=not.a.real.token"
        )
        assert response.status_code == 401

    def test_401_cross_attachment_id(self, fake_db):
        """Token signed for id A, requested as id B → 401 (token mismatch)."""
        from app.core import attachment_tokens

        attachment_tokens.reset_serializer_for_tests()
        token = attachment_tokens.sign_attachment_token("att-A", user_id=1)
        client = _client()
        response = client.get(f"/api/chat/attachments/att-B?token={token}")
        assert response.status_code == 401

    def test_404_unknown_id_even_with_valid_token(self, fake_db):
        """Token verifies but the row has no such id → 404 (not 403)."""
        from app.core import attachment_tokens

        _seed(fake_db, user_id=1)
        attachment_tokens.reset_serializer_for_tests()
        token = attachment_tokens.sign_attachment_token("att-missing", user_id=1)
        client = _client()
        response = client.get(f"/api/chat/attachments/att-missing?token={token}")
        assert response.status_code == 404

    def test_404_cross_user(self, fake_db):
        """User 2's token + user 1's attachment → 404 (NOT 403)."""
        from app.core import attachment_tokens

        _seed(fake_db, user_id=1, project_id=1)
        # Make a real PNG file on disk + register it on user 1's row.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            png_path = tmp.name

        attachment_id = "att-user-1"
        try:
            _insert_message_with_attachment(
                fake_db,
                user_id=1,
                project_id=1,
                session_id=10,
                attachments=[
                    {
                        "id": attachment_id,
                        "kind": "screenshot",
                        "mime": "image/png",
                        "filename": "diagram-1.png",
                        "storage_path": png_path,
                        "source_url": None,
                        "bytes": 40,
                    }
                ],
            )

            # User 2 forges a token for THEIR user_id — token verifies but
            # the row doesn't belong to user 2 → 404.
            attachment_tokens.reset_serializer_for_tests()
            token = attachment_tokens.sign_attachment_token(attachment_id, user_id=2)
            client = _client()
            response = client.get(
                f"/api/chat/attachments/{attachment_id}?token={token}"
            )
            assert response.status_code == 404
        finally:
            os.unlink(png_path)

    def test_200_happy_path(self, fake_db):
        """SCN-ATT-3: valid token + owned attachment → 200 + correct headers."""
        from app.core import attachment_tokens

        _seed(fake_db, user_id=1, project_id=1)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            png_path = tmp.name

        attachment_id = "att-owned"
        try:
            _insert_message_with_attachment(
                fake_db,
                user_id=1,
                project_id=1,
                session_id=10,
                attachments=[
                    {
                        "id": attachment_id,
                        "kind": "screenshot",
                        "mime": "image/png",
                        "filename": "diagram-12345.png",
                        "storage_path": png_path,
                        "source_url": None,
                        "bytes": 40,
                    }
                ],
            )

            attachment_tokens.reset_serializer_for_tests()
            token = attachment_tokens.sign_attachment_token(attachment_id, user_id=1)
            client = _client()
            response = client.get(
                f"/api/chat/attachments/{attachment_id}?token={token}"
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("image/png")
            # SCN-ATT-6: Content-Disposition carries the filename from the row.
            assert "diagram-12345.png" in response.headers["content-disposition"]
            assert "inline" in response.headers["content-disposition"]
            assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
        finally:
            os.unlink(png_path)

    def test_404_no_warning_log_on_missing(self, fake_db, caplog):
        """Info-leak posture: 404 path must NOT emit WARNING-level logs."""
        from app.core import attachment_tokens
        import logging

        _seed(fake_db, user_id=1)
        attachment_tokens.reset_serializer_for_tests()
        token = attachment_tokens.sign_attachment_token("att-nope", user_id=1)
        client = _client()

        with caplog.at_level(logging.WARNING):
            response = client.get(f"/api/chat/attachments/att-nope?token={token}")
        assert response.status_code == 404
        warning_records = [
            r for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert warning_records == []