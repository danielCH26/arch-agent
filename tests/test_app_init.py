"""Tests para app/__init__.py — business logic de proyectos.

PR #102 round 2: el modulo ``app/__init__.py`` tenia 21% de cobertura
(95 statements sin cubrir de 121). Escribimos tests para las 8
funciones puras (get_engram_project_key, format_local,
get_projects_for_user, get_project_name, create_project,
delete_project, get_project, advance_phase, mark_phase_ready)
usando mocks de SessionLocal para no tocar DB real.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import (
    advance_phase,
    create_project,
    delete_project,
    format_local,
    get_engram_project_key,
    get_project,
    get_project_name,
    get_projects_for_user,
    mark_phase_ready,
    PHASES,
)


# --- get_engram_project_key ---------------------------------------------


class TestGetEngramProjectKey:
    def test_default_prefix_when_env_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            assert get_engram_project_key(user_id=7) == "arch-agent-user-7"

    def test_respects_engram_project_env(self):
        with patch.dict("os.environ", {"ENGRAM_PROJECT": "my-app"}):
            assert get_engram_project_key(user_id=42) == "my-app-user-42"

    def test_project_id_arg_is_accepted_but_unused(self):
        """The signature accepts project_id for future use; today it
        is part of the user namespace only."""
        with patch.dict("os.environ", {}, clear=True):
            assert get_engram_project_key(user_id=1, project_id=99) == "arch-agent-user-1"


# --- format_local ---------------------------------------------------------


class TestFormatLocal:
    def test_none_returns_sin_fecha(self):
        assert format_local(None) == "sin fecha"

    def test_naive_datetime_is_treated_as_utc(self):
        # 2024-01-15 18:30 UTC == 13:30 Bogota (UTC-5)
        dt = datetime(2024, 1, 15, 18, 30)
        result = format_local(dt)
        assert "15/01/2024" in result
        assert "01:30" in result or "13:30" in result  # am/pm formatting

    def test_aware_utc_datetime_is_converted(self):
        dt = datetime(2024, 6, 15, 18, 30, tzinfo=timezone.utc)
        result = format_local(dt)
        assert "15/06/2024" in result


# --- get_projects_for_user -----------------------------------------------


class TestGetProjectsForUser:
    def test_returns_query_results_ordered_by_updated_desc(self):
        project_a = MagicMock(name="proj_a")
        project_b = MagicMock(name="proj_b")
        fake_query_chain = MagicMock()
        fake_query_chain.order_by.return_value.all.return_value = [project_a, project_b]

        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value = fake_query_chain

        with patch("app.SessionLocal", return_value=fake_db):
            result = get_projects_for_user(user_id=7)

        assert result == [project_a, project_b]
        fake_db.close.assert_called_once()

    def test_closes_db_on_exception(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.order_by.side_effect = RuntimeError("db boom")

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(RuntimeError, match="db boom"):
                get_projects_for_user(user_id=1)

        fake_db.close.assert_called_once()


# --- get_project_name -----------------------------------------------------


class TestGetProjectName:
    def test_none_project_id_returns_sin_asignar(self):
        assert get_project_name(user_id=1, project_id=None) == "sin asignar"

    def test_returns_project_name_when_found(self):
        project = MagicMock()
        project.name = "Mi Proyecto"
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            assert get_project_name(user_id=1, project_id=5) == "Mi Proyecto"

    def test_returns_sin_asignar_when_not_found(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            assert get_project_name(user_id=1, project_id=999) == "sin asignar"

    def test_closes_db(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            get_project_name(user_id=1, project_id=5)

        fake_db.close.assert_called_once()


# --- create_project -------------------------------------------------------


class TestCreateProject:
    def test_creates_project_with_valid_name(self):
        fake_db = MagicMock()
        # No existing project with the same name
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            project = create_project(user_id=1, name="My App", description="desc")

        fake_db.add.assert_called_once()
        fake_db.commit.assert_called_once()
        fake_db.refresh.assert_called_once()
        assert project.user_id == 1
        assert project.name == "My App"
        assert project.description == "desc"

    def test_strips_name_whitespace(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            project = create_project(user_id=1, name="  Padded  ")

        assert project.name == "Padded"

    def test_rejects_empty_name(self):
        with pytest.raises(Exception) as exc_info:
            create_project(user_id=1, name="   ")

        # ValidationError or any subclass
        assert "vacío" in str(exc_info.value) or "vacio" in str(exc_info.value)

    def test_rejects_duplicate_name(self):
        existing = MagicMock()
        existing.name = "My App"
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = existing

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as match_err:
                create_project(user_id=1, name="My App")

        assert "ya tienes" in str(match_err.value).lower() or "ya" in str(match_err.value).lower()

    def test_rolls_back_on_unexpected_exception(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None
        fake_db.commit.side_effect = RuntimeError("db boom")

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(RuntimeError, match="db boom"):
                create_project(user_id=1, name="My App")

        fake_db.rollback.assert_called_once()
        fake_db.close.assert_called_once()


# --- delete_project -------------------------------------------------------


class TestDeleteProject:
    def test_deletes_existing_project(self):
        project = MagicMock()
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            delete_project(user_id=1, project_id=5)

        fake_db.delete.assert_called_once_with(project)
        fake_db.commit.assert_called_once()

    def test_raises_when_project_not_found(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                delete_project(user_id=1, project_id=999)

        assert "no se encontró" in str(exc_info.value).lower() or "no pertenece" in str(exc_info.value).lower()

    def test_rolls_back_on_db_error(self):
        project = MagicMock()
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project
        fake_db.delete.side_effect = RuntimeError("db boom")

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(RuntimeError, match="db boom"):
                delete_project(user_id=1, project_id=5)

        fake_db.rollback.assert_called_once()


# --- get_project ----------------------------------------------------------


class TestGetProject:
    def test_returns_project_when_found(self):
        project = MagicMock()
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            result = get_project(user_id=1, project_id=5)

        assert result is project

    def test_returns_none_when_not_found(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            assert get_project(user_id=1, project_id=999) is None

    def test_closes_db(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            get_project(user_id=1, project_id=5)

        fake_db.close.assert_called_once()


# --- advance_phase --------------------------------------------------------


class TestAdvancePhase:
    def test_advances_to_next_phase(self):
        project = MagicMock()
        project.current_phase = "requerimientos"
        project.phase_ready = True
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            result = advance_phase(user_id=1, project_id=5)

        assert result is project
        assert project.current_phase == "propuesta"
        assert project.phase_ready is False

    def test_raises_when_project_not_found(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                advance_phase(user_id=1, project_id=999)

        assert "no se encontró" in str(exc_info.value).lower()

    def test_raises_when_phase_not_ready(self):
        project = MagicMock()
        project.current_phase = "requerimientos"
        project.phase_ready = False
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                advance_phase(user_id=1, project_id=5)

        assert "completa" in str(exc_info.value).lower() or "avanzar" in str(exc_info.value).lower()

    def test_raises_when_already_at_last_phase(self):
        project = MagicMock()
        project.current_phase = PHASES[-1]  # "revision"
        project.phase_ready = True
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                advance_phase(user_id=1, project_id=5)

        assert "última" in str(exc_info.value).lower() or "ultima" in str(exc_info.value).lower()

    def test_raises_when_phase_not_recognized(self):
        project = MagicMock()
        project.current_phase = "fase_imaginaria"
        project.phase_ready = True
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                advance_phase(user_id=1, project_id=5)

        assert "no reconocida" in str(exc_info.value).lower() or "manualmente" in str(exc_info.value).lower()


# --- mark_phase_ready -----------------------------------------------------


class TestMarkPhaseReady:
    def test_marks_phase_as_ready(self):
        project = MagicMock()
        project.phase_ready = False
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project

        with patch("app.SessionLocal", return_value=fake_db):
            result = mark_phase_ready(user_id=1, project_id=5)

        assert result is project
        assert project.phase_ready is True
        fake_db.commit.assert_called_once()

    def test_raises_when_project_not_found(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(Exception) as exc_info:
                mark_phase_ready(user_id=1, project_id=999)

        assert "no se encontró" in str(exc_info.value).lower()

    def test_rolls_back_on_db_error(self):
        project = MagicMock()
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = project
        fake_db.commit.side_effect = RuntimeError("db boom")

        with patch("app.SessionLocal", return_value=fake_db):
            with pytest.raises(RuntimeError, match="db boom"):
                mark_phase_ready(user_id=1, project_id=5)

        fake_db.rollback.assert_called_once()
