"""HU10 v2 model tests for ``approvals`` (REQ-SA-27, REQ-SA-16, REQ-SA-30).

Covers the new columns added by migration 0018:
    * ``previous_output`` (REQ-SA-16): JSONB NOT NULL with default '{}'.
    * ``payload`` (REQ-SA-30): JSONB nullable for arbitrary request payload.
    * ``payload_hash`` (REQ-SA-30): VARCHAR(32) nullable idempotency key.

Plus the project_id FK + ON DELETE CASCADE contract from migration 0016
(REQ-SA-27).

NOTE: these tests need a real Postgres database (the engine in
``app/core/database.py`` is created against ``$DATABASE_URL``).
SQLite does not support JSONB or ``ON DELETE CASCADE`` with the
constraints the test exercises. Run via:

    docker compose up -d postgres-app
    pytest tests/models/test_approval.py -v
"""

from __future__ import annotations

import os

import pytest


# Skip unless the runner EXPLICITLY opts in by setting DATABASE_URL to
# something other than the placeholder default in ``app/core/database.py``.
# Without this guard, importing ``app.core`` populates ``DATABASE_URL``
# with the default and the skipif never fires locally (HU10 v3 fix).
_PLACEHOLDER = "postgresql://asistente:asistente@localhost:5432/asistente_db"
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL") == _PLACEHOLDER,
    reason="requires explicit DATABASE_URL pointing at a real Postgres (SQLite does not enforce JSONB or FK cascades)",
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_session():
    """Yield a SQLAlchemy session against the real Postgres test DB.

    Module scope so the schema bootstrap runs once. The migrations runner
    (``migrations/run_migrations.py``) is expected to have already created
    the tables; this fixture only opens the connection.
    """
    from sqlalchemy import text

    from app.core.database import SessionLocal, engine

    # Quick sanity check: Postgres must be reachable.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def fresh_project(db_session):
    """Insert a transient project + session for each test, drop on teardown.

    We avoid reusing the seed projects (id 1..3 in dev DB) so the FK
    assertions are stable.
    """
    from app.models.project import Project
    from app.models.session import UserSession
    from app.models.user import User

    user = (
        db_session.query(User)
        .filter(User.username == "test_approval_model_user")
        .one_or_none()
    )
    if user is None:
        user = User(
            username="test_approval_model_user",
            email="test_approval_model@example.com",
            password_hash="x" * 60,
        )
        db_session.add(user)
        db_session.flush()
    project = Project(
        user_id=user.id,
        name="test-approval-model-project",
        description="for model tests",
        current_phase="requerimientos",
    )
    db_session.add(project)
    db_session.flush()
    yield user, project
    db_session.query(Project).filter(Project.id == project.id).delete()
    db_session.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db_session.query(User).filter(User.id == user.id).delete()
    db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_approval_project_id_fk_required_when_set(db_session, fresh_project):
    """REQ-SA-27: project_id may be NULL (legacy rows) but FK cascade works."""
    from app.core.session_store import record_approval_decision

    user, project = fresh_project
    approval = record_approval_decision(
        db_session,
        user_id=user.id,
        phase="propuesta",
        decision="approve",
        feedback=None,
        project_id=project.id,
    )
    db_session.commit()

    assert approval.id is not None
    assert approval.project_id == project.id
    assert approval.phase == "propuesta"
    assert approval.decision == "approved"  # verb-to-past-tense via DECISION_TO_DB


def test_approval_previous_output_default_is_empty_dict(db_session, fresh_project):
    """REQ-SA-16: previous_output default '{}' on rows where modify didn't run."""
    from app.core.session_store import record_approval_decision

    user, project = fresh_project
    approval = record_approval_decision(
        db_session,
        user_id=user.id,
        phase="refinamiento",
        decision="approve",
        feedback="ok",
        project_id=project.id,
    )
    db_session.commit()

    assert approval.previous_output == {}
    assert approval.payload is None
    assert approval.payload_hash is None


def test_approval_previous_output_populated_on_modify(db_session, fresh_project):
    """REQ-SA-16: previous_output snapshot must be settable on modify."""
    from app.models.approval import Approval

    user, project = fresh_project
    prior = {"mermaid": "graph TD; A-->B", "notes": "v1"}
    approval = Approval(
        session_id=1,  # actual session is created via record_approval_decision below
        project_id=project.id,
        phase="refinamiento",
        decision="modified",
        feedback="use event-driven instead",
        previous_output=prior,
    )
    db_session.add(approval)
    db_session.flush()

    assert approval.previous_output == prior


def test_approval_payload_and_payload_hash_round_trip(db_session, fresh_project):
    """REQ-SA-30: payload + payload_hash persist verbatim."""
    from app.models.approval import Approval

    user, project = fresh_project
    payload = {"trade_offs": {"patron_elegido": "CQRS"}, "advantage": "audit"}
    payload_hash = "a" * 32  # SHA256 hex truncated to 32 chars (16 bytes hex)
    approval = Approval(
        session_id=1,
        project_id=project.id,
        phase="revision",
        decision="modified",
        feedback="switch to CQRS",
        previous_output={},
        payload=payload,
        payload_hash=payload_hash,
    )
    db_session.add(approval)
    db_session.flush()

    assert approval.payload == payload
    assert approval.payload_hash == payload_hash


def test_approval_cascade_delete_with_project(db_session, fresh_project):
    """REQ-SA-27: deleting the project CASCADEs into approvals."""
    from app.core.session_store import record_approval_decision

    user, project = fresh_project
    approval_id = record_approval_decision(
        db_session,
        user_id=user.id,
        phase="propuesta",
        decision="approve",
        feedback=None,
        project_id=project.id,
    ).id
    db_session.commit()

    # Delete the project -- the FK ON DELETE CASCADE must remove the approval row.
    from app.models.project import Project

    db_session.delete(db_session.get(Project, project.id))
    db_session.commit()

    from app.models.approval import Approval

    survivor = (
        db_session.query(Approval).filter(Approval.id == approval_id).one_or_none()
    )
    assert survivor is None, "FK cascade failed: approval row survived project delete"


# ---------------------------------------------------------------------------
# Skips
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires Postgres (DATABASE_URL env var)",
)
def test_database_url_present_marker():
    """Marker so the suite collects even when Postgres is unreachable.

    The actual connectivity check happens in the ``db_session`` fixture
    via the explicit ``SELECT 1`` probe; if Postgres is down, the fixture
    fails with a clear connection error rather than silently skipping.
    """
    assert os.environ.get("DATABASE_URL")