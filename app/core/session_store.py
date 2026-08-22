from app.core.database import SessionLocal
from app.models.session import UserSession
from app.models.project import Project 

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