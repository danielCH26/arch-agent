"""Postgres-backed concurrency test for ``record_decision`` (REQ-SA-31).

HU10 v2 MUST serialise concurrent decisions via ``SELECT ... FOR UPDATE``
on the ``projects`` row. SQLite does not enforce row locks, so this test
MUST run against a real Postgres database -- not SQLite.

Spec-mandated outcome for concurrent IDENTICAL actions (same action +
payload + feedback): the first thread inserts; every other thread blocks
on the row lock, then finds the first thread's committed row via the
idempotency lookup (REQ-SA-30.1) and returns THAT SAME row with
``idempotent=true`` and HTTP 200. Net effect: exactly ONE INSERT + one
idempotent 200 per serialised retry -- NOT one 200 + one 409.

Concurrent DIFFERENT actions (approve + reject) serialise through the
same single lock with no deadlock and no partial state; different
actions are accepted, not conflicted (REQ-SA-30.2): both return 200
with ``idempotent=false``.

Run via::

    docker compose up -d postgres-app
    pytest tests/core/test_phase_decisions_concurrency.py -v

Skip marker: when ``DATABASE_URL`` is missing or the engine cannot connect,
the test session is skipped (the runner must opt in to running this file).
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest


# Skip unless the runner EXPLICITLY opts in by setting DATABASE_URL to
# something other than the placeholder default in ``app/core/database.py``.
# Without this guard, importing ``app.core`` populates ``DATABASE_URL``
# with the default and the skipif never fires locally (HU10 v3 fix).
_PLACEHOLDER = "postgresql://asistente:asistente@localhost:5432/asistente_db"
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL") == _PLACEHOLDER,
    reason="requires explicit DATABASE_URL pointing at a real Postgres (SQLite does not enforce row locks)",
)


# ---------------------------------------------------------------------------
# Test setup
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine():
    """Lazy Postgres engine; raises on first connect if the DB is unreachable."""
    from sqlalchemy import create_engine, text

    from app.core.database import engine

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


@pytest.fixture()
def fresh_project(db_engine):
    """Insert a transient project + session per test, drop on teardown."""
    from app.core.database import SessionLocal
    from app.models.project import Project
    from app.models.session import UserSession
    from app.models.user import User

    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.username == "test_concurrency_user")
            .one_or_none()
        )
        if user is None:
            user = User(
                username="test_concurrency_user",
                email="test_concurrency@example.com",
                password_hash="x" * 60,
            )
            db.add(user)
            db.flush()
        project = Project(
            user_id=user.id,
            name="test-concurrency-project",
            description="for concurrency tests",
            current_phase="requerimientos",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        yield user, project
    finally:
        # Cleanup: drop approvals first (FK), then project, then session.
        try:
            from app.models.approval import Approval

            db.query(Approval).filter(Approval.project_id == project.id).delete()
            db.query(Project).filter(Project.id == project.id).delete()
            db.query(UserSession).filter(UserSession.user_id == user.id).delete()
            db.query(User).filter(User.id == user.id).delete()
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Test: two concurrent identical approves on the same (project, phase)
# ---------------------------------------------------------------------------


def _call_record_decision(
    *, user_id: int, project_id: int, phase: str, action: str = "approve"
):
    """Run record_decision in a worker thread with its own DB session.

    Each thread gets its own ``SessionLocal`` because SQLAlchemy sessions
    are not thread-safe. The helper opens a session, calls
    ``record_decision``, commits, and returns either
    ``PhaseDecisionResult`` (the 200 shape) or the raised exception.
    """
    from app.core.database import SessionLocal
    from app.core.phase_decisions import record_decision

    db = SessionLocal()
    try:
        result = record_decision(
            db,
            user_id=user_id,
            project_id=project_id,
            phase=phase,
            action=action,
        )
        db.commit()
        return result
    except Exception as exc:  # noqa: BLE001 -- we want to forward the typed error
        db.rollback()
        return exc
    finally:
        db.close()


def test_concurrent_double_click_serialises_via_for_update(fresh_project):
    """REQ-SA-31 + REQ-SA-30.1: concurrent IDENTICAL approves serialise via
    FOR UPDATE into exactly ONE INSERT + idempotent 200s.

    The lock winner inserts the row; every serialised thread then finds
    that committed row via the idempotency lookup and returns it with
    ``idempotent=true`` and the SAME ``decision_id``. Assert one row,
    matching ids, and the idempotent flags -- the serialized responses
    intentionally SHARE one payload_hash (that IS the idempotency
    contract working, not a regression).
    """
    from app.core.database import SessionLocal
    from app.models.approval import Approval

    user, project = fresh_project

    N = 4
    barrier = threading.Barrier(N)

    def worker(_i: int):
        # Synchronise the threads so they all hit the lock at once.
        barrier.wait()
        return _call_record_decision(
            user_id=user.id, project_id=project.id, phase="requerimientos"
        )

    with ThreadPoolExecutor(max_workers=N) as pool:
        futures = [pool.submit(worker, i) for i in range(N)]
        results = [f.result() for f in as_completed(futures)]

    successes = [r for r in results if not isinstance(r, Exception)]
    typed_errors = [r for r in results if isinstance(r, Exception)]

    # Identical retries are NEVER rejected: every request returns 200.
    assert not typed_errors, (
        f"concurrent identical approves must not error: {typed_errors!r}"
    )
    assert len(successes) == N

    # All responses carry the SAME decision_id (the first committed row).
    decision_ids = {s.approval.id for s in successes}
    assert len(decision_ids) == 1, (
        f"expected one shared decision_id, got {decision_ids!r}"
    )

    # Exactly the lock winner performed the INSERT (idempotent=False);
    # the N-1 serialised retries returned the same row idempotently.
    idempotent_flags = [s.idempotent for s in successes]
    assert idempotent_flags.count(False) == 1, (
        f"expected exactly one non-idempotent insert, got {idempotent_flags!r}"
    )
    assert idempotent_flags.count(True) == N - 1

    # Exactly ONE approvals row persisted for (project_id, phase).
    db = SessionLocal()
    try:
        rows = (
            db.query(Approval)
            .filter(
                Approval.project_id == project.id,
                Approval.phase == "requerimientos",
            )
            .all()
        )
        assert len(rows) == 1, (
            f"expected exactly one approvals row, got {len(rows)}"
        )
        assert rows[0].id == next(iter(decision_ids))
        # The single row carries project_id (REQ-SA-27).
        assert rows[0].project_id == project.id
    finally:
        db.close()


def test_concurrent_approve_and_reject_serialise_without_conflict(fresh_project):
    """REQ-SA-31 + REQ-SA-30.2: concurrent approve + reject serialise via
    FOR UPDATE without deadlock or partial state.

    Different actions derive different idempotency keys, so BOTH requests
    are accepted (200, ``idempotent=false``) -- NOT 409. Final state:
    exactly 2 approvals rows for (project_id, phase) carrying the 2
    distinct actions.
    """
    from app.core.database import SessionLocal
    from app.models.approval import Approval

    user, project = fresh_project

    barrier = threading.Barrier(2)

    def worker(action: str):
        barrier.wait()
        return action, _call_record_decision(
            user_id=user.id,
            project_id=project.id,
            phase="requerimientos",
            action=action,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, "approve"), pool.submit(worker, "reject")]
        outcomes = [f.result() for f in as_completed(futures)]

    actions = {action for action, _ in outcomes}
    assert actions == {"approve", "reject"}

    # Both actions serialize safely through the single projects row lock:
    # no deadlock, no partial state, no typed error.
    for action, result in outcomes:
        assert not isinstance(result, Exception), (
            f"{action} must not raise under serialisation: {result!r}"
        )
        # Different actions => different hashes => both non-idempotent.
        assert result.idempotent is False

    db = SessionLocal()
    try:
        rows = (
            db.query(Approval)
            .filter(
                Approval.project_id == project.id,
                Approval.phase == "requerimientos",
            )
            .all()
        )
        assert len(rows) == 2, f"expected exactly 2 approvals rows, got {len(rows)}"
        # DB stores the past-tense mapping (DECISION_TO_DB).
        assert {r.decision for r in rows} == {"approved", "rejected"}
        # Every row carries project_id (REQ-SA-27).
        assert all(r.project_id == project.id for r in rows)
    finally:
        db.close()
