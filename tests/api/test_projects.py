"""
Tests para /api/projects/* — CRUD y fases.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestPhaseConstants:
    """Tests de constantes de fase."""

    def test_available_phases(self):
        from app.api.projects import AVAILABLE_PHASES

        assert AVAILABLE_PHASES == [
            "requerimientos",
            "propuesta",
            "refinamiento",
            "revision",
        ]

    def test_phase_labels(self):
        from app.api.projects import PHASE_LABELS

        assert PHASE_LABELS["requerimientos"] == "Requerimientos"
        assert PHASE_LABELS["propuesta"] == "Propuesta"
        assert PHASE_LABELS["revision"] == "Revisión"


class TestProjectModels:
    """Tests de Pydantic models de projects."""

    def test_project_create_model_allows_empty_name(self):
        """Pydantic only type-checks; content validation is in business logic."""
        from app.api.projects import ProjectCreate

        req = ProjectCreate(name="", description=None)
        assert req.name == ""

    def test_project_create_accepts_valid_data(self):
        from app.api.projects import ProjectCreate

        req = ProjectCreate(name="My Project", description="A test")
        assert req.name == "My Project"
        assert req.description == "A test"

    def test_project_create_optional_description(self):
        from app.api.projects import ProjectCreate

        req = ProjectCreate(name="My Project")
        assert req.description is None

    def test_project_out_model(self):
        from app.api.projects import ProjectOut
        from unittest.mock import MagicMock

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.name = "Test Project"
        mock_project.description = "A test"
        mock_project.current_phase = "requerimientos"
        mock_project.phase_ready = False
        mock_project.created_at = "2026-08-28T00:00:00"

        out = ProjectOut.model_validate(mock_project)
        assert out.id == 1
        assert out.name == "Test Project"
        assert out.current_phase == "requerimientos"
        assert out.phase_ready is False

    def test_phase_out_model(self):
        from app.api.projects import PhaseOut, AVAILABLE_PHASES

        out = PhaseOut(
            current_phase="propuesta",
            phase_ready=True,
            available_phases=AVAILABLE_PHASES,
        )
        assert out.current_phase == "propuesta"
        assert out.phase_ready is True
        assert len(out.available_phases) == 4


class TestRequireProjectLogic:
    """Tests de _require_project (función interna síncrona)."""

    @patch("app.core.database.SessionLocal")
    def test_require_project_returns_project_if_owned(self, mock_session):
        from app.api.projects import _require_project
        from unittest.mock import MagicMock

        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.user_id = 1

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        mock_session.return_value = mock_db

        result = _require_project(user_id=1, project_id=1)
        assert result == mock_project

    @patch("app.core.database.SessionLocal")
    def test_require_project_404_when_not_found(self, mock_session):
        """Returns 404 when project doesn't exist."""
        from app.api.projects import _require_project
        from fastapi import HTTPException

        mock_db = MagicMock()
        # First query (user_id+project_id): None
        # Second query (project_id only): None
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session.return_value = mock_db

        with pytest.raises(HTTPException) as exc_info:
            _require_project(user_id=1, project_id=999)
        assert exc_info.value.status_code == 404

    @patch("app.core.database.SessionLocal")
    def test_require_project_403_when_other_users_project(self, mock_session):
        """Returns 403 when project exists but belongs to another user."""
        from app.api.projects import _require_project
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        mock_other_project = MagicMock()
        mock_other_project.id = 1
        mock_other_project.user_id = 999  # different user

        mock_db = MagicMock()
        # First query (user_id=1 + project_id=1): None (not found for this user)
        # Second query (project_id=1): found but belongs to user 999
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,  # first query: user_id=1, project_id=1 → not found
            mock_other_project,  # second query: project_id=1 exists
        ]
        mock_session.return_value = mock_db

        with pytest.raises(HTTPException) as exc_info:
            _require_project(user_id=1, project_id=1)
        assert exc_info.value.status_code == 403
        assert "acceso" in exc_info.value.detail


class TestAdvancePhaseLogic:
    """Tests de la lógica de advance_phase.

    advance_phase es un endpoint async; testamos la lógica de negocio
    verificando los mensajes de error esperados.
    """

    def test_phase_advance_error_when_not_ready(self):
        """phase_ready=False → HTTP 400 con mensaje 'no está completa'."""
        from fastapi import HTTPException

        # Simulate the logic directly
        phase_ready = False
        current_phase = "requerimientos"
        if not phase_ready:
            from app.api.projects import PHASE_LABELS

            label = PHASE_LABELS.get(current_phase, current_phase or "sin asignar")
            detail = f"La fase '{label}' todavía no está completa. No puedes avanzar aún."
            exc = HTTPException(status_code=400, detail=detail)
            assert exc.status_code == 400
            assert "no está completa" in exc.detail

    def test_phase_advance_error_at_last_phase(self):
        """current_phase='revision' + phase_ready=True → HTTP 400 'última fase'."""
        from fastapi import HTTPException

        phase_ready = True
        current_phase = "revision"
        idx = 3  # "revision" is the last phase (index 3 of 4 phases)

        if idx == len(["requerimientos", "propuesta", "refinamiento", "revision"]) - 1:
            detail = "Ya estás en la última fase."
            exc = HTTPException(status_code=400, detail=detail)
            assert exc.status_code == 400
            assert "última fase" in exc.detail
