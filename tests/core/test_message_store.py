"""Unit tests for app/core/message_store.py (F12, REQ-3, SCN-3, SCN-6).

Uses SQLite in-memory with a SQLAlchemy ``Session`` so we exercise the
real ORM mappings without spinning up Postgres. We deliberately create
ONLY the tables the tests touch (``users``, ``sessions``, ``projects``,
``messages``) because ``architect_patterns.tradeoffs`` uses plain JSONB
which the SQLite dialect does not compile.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.message_store import (
    ensure_user_session,
    list_recent,
    save_message,
    _validate_role,
    _coerce_citations,
)
from app.models.message import Message


# Subset of tables the tests touch. We do NOT use ``Base.metadata.create_all``
# because ``architect_patterns.tradeoffs`` is plain JSONB which SQLite
# cannot compile; F12 tests only need ``users / sessions / projects / messages``.
# ``Message.citations`` already uses ``JSON().with_variant(JSONB(), ...)``
# so it compiles cleanly on SQLite.
_TEST_TABLES = ["users", "sessions", "projects", "messages"]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Ensure all models are registered so ``Message`` lands in metadata.
    import app.models  # noqa: F401

    for table_name in _TEST_TABLES:
        table = Base.metadata.tables[table_name]
        # ``checkfirst=True`` keeps re-runs idempotent; create_all on the
        # subset gives us the FK graph without dragging JSONB models in.
        table.create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_user(db, user_id: int = 1):
    """Insert a minimal users row."""
    from app.models.user import User

    db.add(User(id=user_id, username=f"u{user_id}", email=f"u{user_id}@x", password_hash="x"))
    db.commit()


def _seed_user_project(db, user_id: int, project_id: int):
    from app.models.project import Project

    db.add(Project(id=project_id, user_id=user_id, name=f"P{project_id}"))
    db.commit()


class TestSaveMessage:
    def test_returns_message_with_id(self, db):
        _seed_user(db)
        _seed_user_project(db, user_id=1, project_id=1)
        sid = ensure_user_session(db, 1)

        msg = save_message(db, sid, project_id=1, user_id=1, role="user", content="hola")

        assert msg.id is not None
        assert msg.role == "user"
        assert msg.content == "hola"
        assert msg.citations == []
        assert msg.engram_observation_id is None

    def test_role_validation_rejects_unknown(self):
        with pytest.raises(ValueError, match="role must be one of"):
            _validate_role("admin")

    def test_citations_none_normalises_to_empty_list(self):
        assert _coerce_citations(None) == []

    def test_citations_list_round_trips(self):
        citations = [{"source_type": "pattern", "name": "BFF"}]
        assert _coerce_citations(citations) == citations

    def test_citations_dict_round_trips(self):
        citations = {"source_type": "pattern"}
        assert _coerce_citations(citations) == citations

    def test_citations_invalid_falls_back_to_empty(self):
        class NotJsonable:
            pass

        assert _coerce_citations(NotJsonable()) == []

    def test_flush_does_not_commit_so_caller_owns_tx(self, db):
        _seed_user(db)
        sid = ensure_user_session(db, 1)
        msg = save_message(db, sid, project_id=None, user_id=1, role="user", content="x")

        # After flush the row is "persistent" (has an id) but NOT committed
        # — the caller controls the transaction boundary (REQ-4). We assert
        # the object is reachable from the session and has an id, but the
        # session is still not in "committed" state. The rollback below
        # proves the row never reached the DB without an explicit commit.
        assert msg.id is not None
        assert msg in db

        db.rollback()
        # New session against the same engine — the message must NOT be there.
        from app.core.message_store import list_recent
        from sqlalchemy.orm import sessionmaker

        Engine = db.get_bind()
        Session = sessionmaker(bind=Engine)
        fresh = Session()
        try:
            assert list_recent(fresh, sid, limit=10) == []
        finally:
            fresh.close()


class TestListRecent:
    def test_orders_newest_first(self, db):
        _seed_user(db)
        sid = ensure_user_session(db, 1)

        for text in ["first", "second", "third"]:
            save_message(db, sid, project_id=None, user_id=1, role="user", content=text)
            db.commit()

        rows = list_recent(db, sid, limit=5)
        contents = [r.content for r in rows]
        assert contents == ["third", "second", "first"]

    def test_default_limit_is_5(self, db):
        _seed_user(db)
        sid = ensure_user_session(db, 1)
        for i in range(8):
            save_message(db, sid, project_id=None, user_id=1, role="user", content=f"m{i}")
            db.commit()

        rows = list_recent(db, sid)
        assert len(rows) == 5

    def test_limit_clamped_to_min_1(self, db):
        _seed_user(db)
        sid = ensure_user_session(db, 1)
        save_message(db, sid, project_id=None, user_id=1, role="user", content="only")
        db.commit()

        rows = list_recent(db, sid, limit=0)
        assert len(rows) == 1

    def test_session_id_scopes_results(self, db):
        """Cross-user isolation: list_recent must NOT leak across sessions."""
        _seed_user(db, user_id=1)
        _seed_user_project(db, user_id=1, project_id=1)
        _seed_user(db, user_id=2)
        _seed_user_project(db, user_id=2, project_id=2)

        sid1 = ensure_user_session(db, 1)
        sid2 = ensure_user_session(db, 2)

        save_message(db, sid1, project_id=1, user_id=1, role="user", content="user1-msg")
        save_message(db, sid2, project_id=2, user_id=2, role="user", content="user2-msg")
        db.commit()

        rows_u1 = list_recent(db, sid1, limit=10)
        rows_u2 = list_recent(db, sid2, limit=10)

        assert [r.content for r in rows_u1] == ["user1-msg"]
        assert [r.content for r in rows_u2] == ["user2-msg"]


class TestEnsureUserSession:
    def test_returns_existing_session_id(self, db):
        _seed_user(db)
        sid_first = ensure_user_session(db, 1)
        sid_second = ensure_user_session(db, 1)
        assert sid_first == sid_second

    def test_creates_session_when_missing(self, db):
        from app.models.user import User

        db.add(User(id=99, username="u99", email="u99@x", password_hash="x"))
        db.commit()

        sid = ensure_user_session(db, 99)
        assert isinstance(sid, int)
        assert sid > 0
