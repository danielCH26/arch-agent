"""Endpoint tests for the HU10 v2 routes added to ``app/api/projects.py``.

Covers:
    * REQ-SA-12, REQ-SA-26: GET /api/projects/{id}/phases returns
      ``pending_decision``.
    * REQ-SA-13, REQ-SA-14, REQ-SA-15: POST .../phase/{phase}/decision
      shape on 200.
    * REQ-SA-28: phase_mismatch -> 409 with typed body, current_phase in detail.
    * REQ-SA-30: idempotency_key honored; identical retry returns
      ``idempotent=True``.
    * REQ-SA-36: /advance 409s without HU10 approval row for HU10-owned phases;
      F05-owned ``requerimientos`` skips the gate.
    * REQ-SA-23: POST /mark-ready returns 404.

The tests mock ``record_decision`` / ``assert_hu10_approval_for_current_phase``
and the DB so they run without Postgres (the Postgres-backed concurrency
test lives in ``test_phase_decisions_concurrency.py``).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server import app  # noqa: F401  (imported to register the router)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI TestClient (httpx-based) against the in-process app."""
    return TestClient(app)


@pytest.fixture()
def auth_headers(mock_user, monkeypatch):
    """Patch get_current_user so we don't need to round-trip JWT."""
    from app.api import dependencies

    async def _fake_get_current_user():
        return {
            "user_id": mock_user.id,
            "username": mock_user.username,
            "jti": None,
        }

    app.dependency_overrides[dependencies.get_current_user] = _fake_get_current_user
    yield {"Authorization": "Bearer test-token"}
    app.dependency_overrides.pop(dependencies.get_current_user, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_row(*, project_id: int = 7, current_phase: str = "propuesta", phase_ready: bool = False):
    p = MagicMock()
    p.id = project_id
    p.current_phase = current_phase
    p.phase_ready = phase_ready
    return p


# ---------------------------------------------------------------------------
# REQ-SA-12, REQ-SA-26: GET /api/projects/{id}/phases
# ---------------------------------------------------------------------------


def test_get_phases_includes_pending_decision(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-12.1: pending_decision surfaces the current phase's last decision."""
    project = _project_row(current_phase="refinamiento", phase_ready=False)

    pending = MagicMock()
    pending.phase = "refinamiento"
    pending.since = datetime(2026, 9, 27, 22, 0, 0)
    pending.last_decision = "approved"
    pending.last_decided_at = datetime(2026, 9, 27, 22, 0, 0)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    with patch("app.core.phase_decisions.get_pending_decision", return_value=pending), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.get(
            f"/api/projects/{project.id}/phases",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_phase"] == "refinamiento"
    assert body["available_phases"] == [
        "requerimientos",
        "propuesta",
        "refinamiento",
        "revision",
        "final",
    ]
    assert body["pending_decision"] is not None
    assert body["pending_decision"]["phase"] == "refinamiento"
    assert body["pending_decision"]["last_decision"] == "approved"


def test_get_phases_pending_decision_present_when_no_record(client, auth_headers, mock_user, monkeypatch):
    """SCN-SA-12.1: pending_decision is present when no approved decision exists
    for HU10-owned phase (propuesta, refinamiento, revision, final)."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    project = _project_row(current_phase="refinamiento", phase_ready=False)

    pending = MagicMock()
    pending.phase = "refinamiento"
    pending.since = datetime(2026, 9, 27, 22, 0, 0, tzinfo=timezone.utc)
    pending.last_decision = None
    pending.last_decided_at = None

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project
    db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("app.core.phase_decisions.get_pending_decision", return_value=pending), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.get(
            f"/api/projects/{project.id}/phases",
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()["pending_decision"] is not None
    assert response.json()["pending_decision"]["phase"] == "refinamiento"


# ---------------------------------------------------------------------------
# REQ-SA-13, REQ-SA-14, REQ-SA-15: POST .../phase/{phase}/decision happy path
# ---------------------------------------------------------------------------


def test_post_phase_decision_approve_happy_path(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-15: 200 returns decision_id, next_phase, decided_at, idempotent."""
    project = _project_row(current_phase="propuesta", phase_ready=False)

    approval = MagicMock()
    approval.id = 42
    approval.created_at = datetime(2026, 9, 27, 22, 0, 0)

    result = MagicMock()
    result.approval = approval
    result.idempotent = False
    result.next_phase = "refinamiento"
    result.phase_ready = True

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    with patch("app.core.phase_decisions.record_decision", return_value=result), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/phase/propuesta/decision",
            json={"action": "approve"},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_id"] == 42
    assert body["action"] == "approve"
    assert body["phase"] == "propuesta"
    assert body["next_phase"] == "refinamiento"
    assert body["idempotent"] is False


def test_post_phase_decision_idempotent_retry(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-30.1: identical retry within 60s returns idempotent=True."""
    project = _project_row(current_phase="propuesta", phase_ready=False)

    approval = MagicMock()
    approval.id = 99
    approval.created_at = datetime(2026, 9, 27, 22, 0, 0)

    result = MagicMock()
    result.approval = approval
    result.idempotent = True
    result.next_phase = "refinamiento"
    result.phase_ready = False

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    with patch("app.core.phase_decisions.record_decision", return_value=result), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/phase/propuesta/decision",
            json={"action": "approve"},
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["idempotent"] is True
    assert body["decision_id"] == 99


# ---------------------------------------------------------------------------
# REQ-SA-28: phase_mismatch -> 409 with typed body
# ---------------------------------------------------------------------------


def test_post_phase_decision_phase_mismatch_returns_409(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-28: phase != current_phase -> 409 + detail.error=phase_mismatch."""
    project = _project_row(current_phase="requerimientos", phase_ready=False)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    from app.core.phase_decisions import PhaseMismatchError

    with patch(
        "app.core.phase_decisions.record_decision",
        side_effect=PhaseMismatchError(
            current_phase="requerimientos", requested_phase="refinamiento"
        ),
    ), patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/phase/refinamiento/decision",
            json={"action": "approve"},
            headers=auth_headers,
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "phase_mismatch"
    assert detail["current_phase"] == "requerimientos"
    assert detail["requested_phase"] == "refinamiento"


# ---------------------------------------------------------------------------
# REQ-SA-14: invalid action / missing feedback
# ---------------------------------------------------------------------------


def test_post_phase_decision_rejects_unknown_action(client, auth_headers, mock_user):
    """REQ-SA-14: action not in {approve,modify,reject} -> 422."""
    response = client.post(
        "/api/projects/7/phase/propuesta/decision",
        json={"action": "merge"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_post_phase_decision_modify_requires_feedback(client, auth_headers, mock_user):
    """REQ-SA-14: modify without feedback -> 400."""
    response = client.post(
        "/api/projects/7/phase/propuesta/decision",
        json={"action": "modify", "feedback": ""},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_post_phase_decision_rejects_unknown_phase(client, auth_headers, mock_user):
    """REQ-SA-4: phase not in AVAILABLE_PHASES -> 422."""
    response = client.post(
        "/api/projects/7/phase/diagram/decision",
        json={"action": "approve"},
        headers=auth_headers,
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# REQ-SA-36: /advance single-owner enforcement
# ---------------------------------------------------------------------------


def test_advance_blocks_hu10_phase_without_approval(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-36: HU10-owned phase w/o approval -> 409 phase_not_approved."""
    project = _project_row(current_phase="propuesta", phase_ready=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    from app.core.phase_decisions import PhaseNotApprovedError

    with patch(
        "app.core.phase_decisions.assert_hu10_approval_for_current_phase",
        side_effect=PhaseNotApprovedError(phase="propuesta"),
    ), patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/advance",
            headers=auth_headers,
        )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "phase_not_approved"
    assert detail["phase"] == "propuesta"


def test_advance_passes_f05_owned_phase(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-36: `requerimientos` (F05-owned) skips the HU10 gate."""
    project = _project_row(current_phase="requerimientos", phase_ready=True)
    db = MagicMock()
    # Mock the execute() method for FOR UPDATE query
    db.execute.return_value.scalar_one_or_none.return_value = project

    # Mock assert_hu10_approval_for_current_phase as a no-op so we can detect
    # the call; F05's path must NOT trigger it.
    with patch(
        "app.core.phase_decisions.assert_hu10_approval_for_current_phase"
    ) as mock_gate, patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/advance",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    mock_gate.assert_called_once()
    # Gate must NOT raise because the phase is F05-owned.


def test_advance_blocks_when_phase_ready_false(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-2 / REQ-SA-15: cannot advance without phase_ready."""
    project = _project_row(current_phase="requerimientos", phase_ready=False)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    with patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/advance",
            headers=auth_headers,
        )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# REQ-SA-23: POST /mark-ready retired (404)
# ---------------------------------------------------------------------------


def test_mark_ready_returns_404(client, auth_headers, mock_user):
    """REQ-SA-23: POST /mark-ready returns 404 with replacement hint."""
    response = client.post(
        "/api/projects/7/mark-ready",
        headers=auth_headers,
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["error"] == "endpoint_removed"
    assert "replacement" in detail


# ---------------------------------------------------------------------------
# Re-review fixes: detached session, timestamps, no str(exc) leak
# ---------------------------------------------------------------------------


def test_post_phase_decision_reads_approval_before_session_closes(
    client, auth_headers, mock_user
):
    """Regression: the handler used to read ``result.approval.id`` /
    ``created_at`` AFTER ``db.commit()`` + ``db.close()``.

    ``SessionLocal`` expires attributes on commit and ``close()`` detaches the
    row, so every decision answered 500 (DetachedInstanceError) even though it
    had been saved, and every idempotent retry failed the same way. The other
    tests here mock the session, so they could never see it; this one uses a
    real SQLAlchemy session (SQLite, same ``sessionmaker`` defaults as
    ``app.core.database.SessionLocal``) with a stand-in ORM row.
    """
    from types import SimpleNamespace

    from sqlalchemy import Column, DateTime, Integer, create_engine, func
    from sqlalchemy.orm import declarative_base, sessionmaker
    from sqlalchemy.pool import StaticPool

    Base = declarative_base()

    class FakeApproval(Base):
        __tablename__ = "fake_approvals"
        id = Column(Integer, primary_key=True)
        created_at = Column(DateTime, server_default=func.now())

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    real_session = sessionmaker(bind=engine)  # expire_on_commit=True (default)

    def fake_record_decision(db, **_kwargs):
        row = FakeApproval()
        db.add(row)
        db.flush()
        return SimpleNamespace(
            approval=row,
            idempotent=False,
            next_phase="refinamiento",
            phase_ready=True,
        )

    with patch(
        "app.core.phase_decisions.record_decision", side_effect=fake_record_decision
    ), patch("app.api.projects._require_project", return_value=None), patch(
        "app.api.projects.SessionLocal", side_effect=real_session
    ):
        response = client.post(
            "/api/projects/7/phase/propuesta/decision",
            json={"action": "approve"},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_id"] == 1
    assert body["next_phase"] == "refinamiento"
    # decided_at carries an explicit offset (naive DB timestamp read as UTC).
    assert body["decided_at"].endswith("+00:00")


def test_get_phases_timestamps_share_the_same_utc_offset(
    client, auth_headers, mock_user
):
    """``since`` got ``+00:00`` but ``last_decided_at`` did not, so the browser
    parsed one as UTC and the other as local time."""
    project = _project_row(current_phase="refinamiento", phase_ready=False)

    pending = MagicMock()
    pending.phase = "refinamiento"
    pending.since = datetime(2026, 9, 27, 22, 0, 0)  # naive, as the DB returns it
    pending.last_decision = "rejected"
    pending.last_decided_at = datetime(2026, 9, 27, 22, 0, 0)

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project
    db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("app.core.phase_decisions.get_pending_decision", return_value=pending), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.get(f"/api/projects/{project.id}/phases", headers=auth_headers)

    assert response.status_code == 200, response.text
    pending_out = response.json()["pending_decision"]
    assert pending_out["since"].endswith("+00:00")
    assert pending_out["last_decided_at"].endswith("+00:00")


def test_get_phases_pending_without_decisions_has_null_timestamps(
    client, auth_headers, mock_user
):
    project = _project_row(current_phase="refinamiento", phase_ready=False)

    pending = MagicMock()
    pending.phase = "refinamiento"
    pending.since = None
    pending.last_decision = None
    pending.last_decided_at = None

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project
    db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("app.core.phase_decisions.get_pending_decision", return_value=pending), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.get(f"/api/projects/{project.id}/phases", headers=auth_headers)

    assert response.status_code == 200, response.text
    pending_out = response.json()["pending_decision"]
    assert pending_out["since"] is None
    assert pending_out["last_decided_at"] is None


def test_advance_unexpected_error_does_not_leak_exception_text(
    client, auth_headers, mock_user
):
    """REQ-SA-34: the 500 fallback must never return ``str(exc)``."""
    project = _project_row(current_phase="propuesta", phase_ready=True)
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = project

    with patch(
        "app.core.phase_decisions.assert_hu10_approval_for_current_phase",
        side_effect=RuntimeError("connection string password=hunter2"),
    ), patch("app.api.projects.SessionLocal", return_value=db):
        response = client.post(
            f"/api/projects/{project.id}/advance",
            headers=auth_headers,
        )

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["detail"] == {"error": "internal_error"}
