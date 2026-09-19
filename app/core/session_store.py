from sqlalchemy.orm import Session
from app.core.message_store import ensure_user_session
from app.core.database import SessionLocal
from app.models.session import UserSession
from app.models.project import Project
from app.models.approval import Approval

def save_session_state(user_id: int, project_id: int = None, active_phase: str = None, engram_state: dict = None):
    db = SessionLocal()
    try:
        session = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session is None:
            session = UserSession(user_id=user_id)
            db.add(session)
        if project_id is not None:
            session.project_id = project_id
        if active_phase is not None:
            session.active_phase = active_phase
        if engram_state is not None:
            session.engram_state = engram_state
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def load_session_state(user_id: int) -> dict | None:
    db = SessionLocal()
    try:
        session = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session is None:
            return None
        return {
            "project_id": session.project_id,
            "active_phase": session.active_phase,
            "engram_state": session.engram_state,
        }
    finally:
        db.close()


DECISION_TO_DB = {
    "approve": "approved",
    "modify": "modified",
    "reject": "rejected",
}


def record_approval_decision(
    db: Session,
    *,
    user_id: int,
    phase: str,
    decision: str,
    feedback: str | None = None,
    project_id: int | None = None,
) -> Approval:
    """Registra una fila en `approvals` para `phase`, creando la
    `UserSession` si todavía no existe (via `ensure_user_session`) en
    vez de exigir que ya haya una y tirar 400 (criterio unificado,
    ver nota en diagrams.py::decide_diagram).

    No hace `db.commit()` -- el caller controla la transacción, igual
    que antes lo hacían diagrams.py/proposals.py/elicitation.py cada
    uno con su propio `db.add(...)` + commit.

    `project_id` (migration 0016): `sessions` es una fila por usuario, no
    por proyecto, así que sin esto una aprobación del proyecto A "contamina"
    al proyecto B del mismo usuario (hallazgo #1, revisión
    feature/hu6-diagrama). Todos los callers (elicitation.py, proposals.py,
    diagrams.py) deben pasarlo -- queda opcional solo para no romper código
    viejo que aún no lo pase explícitamente.
    """
    session_id = ensure_user_session(db, user_id)

    approval = Approval(
        session_id=session_id,
        project_id=project_id,
        phase=phase,
        decision=DECISION_TO_DB[decision],
        feedback=feedback,
    )
    db.add(approval)
    db.flush()
    return approval