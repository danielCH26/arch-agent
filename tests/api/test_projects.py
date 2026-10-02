"""
Tests para /api/projects/* — CRUD y fases.

Helpers:
- ``_make_client`` boots a ``TestClient`` against the real ``server.app`` and
  wires both an auth dependency override (``get_current_user``) and a fake
  ``app.core.database.SessionLocal``. The returned ``(client, mock_db)`` tuple
  lets each test arrange DB query results without touching the real Postgres.
"""

import pytest
from unittest.mock import MagicMock, patch
from contextlib import contextmanager
from typing import Any


@contextmanager
def _make_client(
    user: dict | None = None,
    session_local_side_effect: Any = None,
):
    """Yield ``(client, mock_db)`` with auth and DB mocked.

    Usage::

        with _make_client(user={"user_id": 1, ...}) as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.get("/api/projects/1")
            assert resp.status_code == 200

    ``session_local_side_effect`` is forwarded to ``SessionLocal`` mock so
    you can make ``SessionLocal()`` raise (e.g. ``IntegrityError``).
    """
    from fastapi.testclient import TestClient
    from server import app
    from app.api.dependencies import get_current_user

    if user is None:
        user = {"user_id": 1, "username": "laura", "jti": None}

    app.dependency_overrides[get_current_user] = lambda: user
    mock_db = MagicMock()
    with patch("app.core.database.SessionLocal") as mock_session:
        if session_local_side_effect is not None:
            mock_session.side_effect = session_local_side_effect
        else:
            mock_session.return_value = mock_db
        client = TestClient(app, raise_server_exceptions=False)
        try:
            yield client, mock_db
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Existing class — TestRequireProjectLogic kept verbatim above
# (see lines 1–142 of original test_projects.py for context)
# ---------------------------------------------------------------------------


class TestListProjectsEndpoint:
    """Integration tests for GET /api/projects."""

    def test_list_returns_user_projects_in_desc_order(self):
        p_old = MagicMock()
        p_old.id = 1
        p_old.name = "old"
        p_old.description = None
        p_old.current_phase = "requerimientos"
        p_old.phase_ready = False
        # Real datetime so the response model can call .isoformat()
        from datetime import datetime
        p_old.created_at = datetime(2026, 1, 1, 0, 0, 0)
        p_new = MagicMock()
        p_new.id = 2
        p_new.name = "new"
        p_new.description = "fresh"
        p_new.current_phase = "propuesta"
        p_new.phase_ready = True
        p_new.created_at = datetime(2026, 9, 1, 0, 0, 0)

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [p_old, p_new]
            resp = client.get("/api/projects")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert body[0]["name"] == "old"
        assert body[1]["name"] == "new"
        assert body[1]["phase_ready"] is True

    def test_list_returns_empty_array_when_no_projects(self):
        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            resp = client.get("/api/projects")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_project_with_none_created_at_returns_empty_string(self):
        p = MagicMock()
        p.id = 1
        p.name = "x"
        p.description = None
        p.current_phase = "requerimientos"
        p.phase_ready = False
        p.created_at = None

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [p]
            resp = client.get("/api/projects")

        assert resp.status_code == 200
        assert resp.json()[0]["created_at"] == ""


class TestCreateProjectEndpoint:
    """Integration tests for POST /api/projects."""

    def test_create_project_success(self):
        from datetime import datetime

        def fake_refresh(p):
            # Real Project ORM sets attributes on refresh; mimic that.
            p.__dict__.update({
                "id": 99,
                "name": "New Project",
                "description": "desc",
                "current_phase": "requerimientos",
                "phase_ready": False,
                "created_at": datetime(2026, 10, 1),
            })

        with _make_client() as (client, mock_db):
            # First query (duplicate check): None (no duplicate)
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_db.refresh.side_effect = fake_refresh

            resp = client.post(
                "/api/projects",
                json={"name": "New Project", "description": "desc"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "New Project"
        assert body["current_phase"] == "requerimientos"
        assert body["phase_ready"] is False
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_project_rejects_empty_name(self):
        with _make_client() as (client, _mock_db):
            resp = client.post("/api/projects", json={"name": "   ", "description": "x"})

        assert resp.status_code == 400
        assert "vacío" in resp.json()["detail"]

    def test_create_project_rejects_whitespace_only_name(self):
        with _make_client() as (client, _mock_db):
            resp = client.post("/api/projects", json={"name": "\t\n", "description": None})

        assert resp.status_code == 400

    def test_create_project_returns_409_for_duplicate_name(self):
        existing = MagicMock()
        existing.id = 5
        existing.name = "Dup"

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = existing
            resp = client.post("/api/projects", json={"name": "Dup", "description": None})

        assert resp.status_code == 409
        assert "Dup" in resp.json()["detail"]
        mock_db.add.assert_not_called()

    def test_create_project_handles_db_failure_as_500(self):
        """Generic DB failure during commit surfaces as 500 (handle_db_errors path)."""
        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_db.commit.side_effect = RuntimeError("db exploded")
            resp = client.post("/api/projects", json={"name": "Doomed", "description": None})

        # handle_db_errors decorator catches non-DB exceptions as 500
        assert resp.status_code == 500


class TestGetProjectEndpoint:
    """Integration tests for GET /api/projects/{id}."""

    def test_get_owned_project_returns_it(self):
        proj = MagicMock()
        proj.id = 1
        proj.name = "Mine"
        proj.description = None
        proj.current_phase = "requerimientos"
        proj.phase_ready = False
        proj.created_at = None

        with _make_client() as (client, mock_db):
            # _require_project issues one query (user_id+id) that finds the project
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.get("/api/projects/1")

        assert resp.status_code == 200
        assert resp.json()["name"] == "Mine"

    def test_get_unowned_project_returns_403(self):
        with _make_client() as (client, mock_db):
            # First query (user+id): None; second query (id): exists but other user
            other = MagicMock()
            mock_db.query.return_value.filter.return_value.first.side_effect = [None, other]
            resp = client.get("/api/projects/7")

        assert resp.status_code == 403

    def test_get_missing_project_returns_404(self):
        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = None
            resp = client.get("/api/projects/9999")

        assert resp.status_code == 404


class TestDeleteProjectEndpoint:
    """Integration tests for DELETE /api/projects/{id}."""

    def test_delete_owned_project_returns_204(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.delete("/api/projects/1")

        assert resp.status_code == 204
        mock_db.delete.assert_called_once_with(proj)
        mock_db.commit.assert_called_once()

    def test_delete_unowned_project_returns_403(self):
        with _make_client() as (client, mock_db):
            other = MagicMock()
            mock_db.query.return_value.filter.return_value.first.side_effect = [None, other]
            resp = client.delete("/api/projects/7")

        assert resp.status_code == 403
        mock_db.delete.assert_not_called()


class TestGetPhaseEndpoint:
    """Integration tests for GET /api/projects/{id}/phase."""

    def test_get_phase_returns_current_phase(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "refinamiento"
        proj.phase_ready = True

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.get("/api/projects/1/phase")

        assert resp.status_code == 200
        body = resp.json()
        assert body["current_phase"] == "refinamiento"
        assert body["phase_ready"] is True
        assert len(body["available_phases"]) == 4

    def test_get_phase_returns_default_when_current_phase_is_none(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = None
        proj.phase_ready = False

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.get("/api/projects/1/phase")

        assert resp.status_code == 200
        assert resp.json()["current_phase"] == "requerimientos"


class TestAdvancePhaseEndpoint:
    """Integration tests for POST /api/projects/{id}/advance."""

    def test_advance_phase_success(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "requerimientos"
        proj.phase_ready = True

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 200
        body = resp.json()
        assert body["current_phase"] == "propuesta"
        assert body["phase_ready"] is False
        assert "Propuesta" in body["message"]
        mock_db.commit.assert_called_once()

    def test_advance_phase_when_not_ready_returns_400(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "requerimientos"
        proj.phase_ready = False

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 400
        assert "no está completa" in resp.json()["detail"]

    def test_advance_phase_at_last_phase_returns_400(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "revision"
        proj.phase_ready = True

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 400
        assert "última fase" in resp.json()["detail"]

    def test_advance_phase_with_unknown_phase_returns_400(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "garbage"
        proj.phase_ready = True

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 400
        assert "no reconocida" in resp.json()["detail"]

    def test_advance_phase_returns_403_when_project_belongs_to_other(self):
        with _make_client() as (client, mock_db):
            other = MagicMock()
            mock_db.query.return_value.filter.return_value.first.side_effect = [None, other]
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 403

    def test_advance_phase_handles_db_failure_as_500(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "requerimientos"
        proj.phase_ready = True

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            mock_db.commit.side_effect = RuntimeError("db exploded")
            resp = client.post("/api/projects/1/advance")

        assert resp.status_code == 500


class TestMarkReadyEndpoint:
    """Integration tests for POST /api/projects/{id}/mark-ready."""

    def test_mark_ready_success(self):
        proj = MagicMock()
        proj.id = 1
        proj.user_id = 1
        proj.current_phase = "requerimientos"
        proj.phase_ready = False

        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = proj
            resp = client.post("/api/projects/1/mark-ready")

        assert resp.status_code == 200
        body = resp.json()
        assert body["phase_ready"] is True
        assert "completa" in body["message"]
        assert proj.phase_ready is True  # mutated in place
        mock_db.commit.assert_called_once()

    def test_mark_ready_returns_404_when_missing(self):
        with _make_client() as (client, mock_db):
            mock_db.query.return_value.filter.return_value.first.return_value = None
            resp = client.post("/api/projects/999/mark-ready")

        assert resp.status_code == 404

    def test_mark_ready_returns_403_when_project_belongs_to_other(self):
        with _make_client() as (client, mock_db):
            other = MagicMock()
            mock_db.query.return_value.filter.return_value.first.side_effect = [None, other]
            resp = client.post("/api/projects/7/mark-ready")

        assert resp.status_code == 403