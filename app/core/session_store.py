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

# Inverso de DECISION_TO_DB: lo que guarda la DB -> lo que habla la API.
DECISION_FROM_DB = {v: k for k, v in DECISION_TO_DB.items()}


def latest_diagram_decisions(
    db: Session, *, project_id: int, attachment_ids: list[str]
) -> dict[str, str]:
    """Última decisión registrada por diagrama, como ``{attachment_id:
    "approve" | "modify" | "reject"}``. Los diagramas sin decisión no
    aparecen en el resultado.

    Una sola consulta para todos los ids (la usan el historial del chat y el
    historial de diagramas). Filtra por ``project_id`` además de por
    ``attachment_id`` para no mezclar proyectos.
    """
    ids = [a for a in attachment_ids if a]
    if not ids:
        return {}

    rows = (
        db.query(Approval.attachment_id, Approval.decision)
        .filter(
            Approval.phase == "diagram",
            Approval.project_id == project_id,
            Approval.attachment_id.in_(ids),
        )
        .order_by(Approval.id.asc())
        .all()
    )
    # order_by id asc + dict => la última fila de cada diagrama pisa a las anteriores.
    return {
        row.attachment_id: DECISION_FROM_DB.get(row.decision, row.decision)
        for row in rows
    }


def record_approval_decision(
    db: Session,
    *,
    user_id: int,
    phase: str,
    decision: str,
    feedback: str | None = None,
    project_id: int | None = None,
    attachment_id: str | None = None,
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

    `attachment_id` (migration 0017): solo para la fase "diagram" -- UUID del
    adjunto sobre el que se decidió, para que la decisión sea POR diagrama y
    no solo por proyecto.
    """
    session_id = ensure_user_session(db, user_id)

    approval = Approval(
        session_id=session_id,
        project_id=project_id,
        phase=phase,
        decision=DECISION_TO_DB[decision],
        feedback=feedback,
        attachment_id=attachment_id,
    )
    db.add(approval)
    db.flush()
    return approval