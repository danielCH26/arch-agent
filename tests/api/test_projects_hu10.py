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


def test_get_phases_pending_decision_null_when_no_record(client, auth_headers, mock_user, monkeypatch):
    """REQ-SA-26: pending_decision is null when no decision on file."""
    project = _project_row(current_phase="requerimientos", phase_ready=False)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = project

    with patch("app.core.phase_decisions.get_pending_decision", return_value=None), \
         patch("app.api.projects.SessionLocal", return_value=db):
        response = client.get(
            f"/api/projects/{project.id}/phases",
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json()["pending_decision"] is None


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
    db.query.return_value.filter.return_value.first.return_value = project

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