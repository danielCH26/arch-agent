"""Persistencia del estado de la elicitación guiada por proyecto."""

from __future__ import annotations

from copy import deepcopy

from app.models.session import UserSession

STATE_KEY = "elicitation"


def get_project_elicitation_state(session: UserSession | None, project_id: int) -> dict:
    """Obtiene el estado aislado de un proyecto sin mutar el JSON de SQLAlchemy."""
    if session is None or not session.engram_state:
        return {}
    all_states = session.engram_state.get(STATE_KEY, {})
    return deepcopy(all_states.get(str(project_id), {}))


def save_project_elicitation_state(
    db, user_id: int, project_id: int, state: dict, active_phase: str = "requerimientos"
) -> None:
    """Guarda el estado sin borrar las sesiones de otros proyectos del usuario."""
    session = db.query(UserSession).filter(UserSession.user_id == user_id).first()
    if session is None:
        session = UserSession(user_id=user_id)
        db.add(session)

    engram_state = deepcopy(session.engram_state or {})
    project_states = dict(engram_state.get(STATE_KEY, {}))
    project_states[str(project_id)] = deepcopy(state)
    engram_state[STATE_KEY] = project_states

    session.project_id = project_id
    session.active_phase = active_phase
    # Reasignar el dict asegura que SQLAlchemy persista la modificación JSON.
    session.engram_state = engram_state
