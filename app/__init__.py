"""
Business logic module — aplication-level helpers.

Originally part of app.py (Chainlit entry). After migrating to REST API (F25),
this module retains pure business-logic functions used by the rest of the
system (API routes, tests, etc.).

Functions in this module do NOT import chainlit and do NOT depend on it.
"""

import os
import logging
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv

_env_path = (__import__("pathlib").Path(__file__).parent / ".env").resolve()
load_dotenv()

from app.core.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.auth.validators import ValidationError

logger = logging.getLogger(__name__)

BOGOTA_TZ = __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/Bogota")


# --- Engram helpers --------------------------------------------------------

def get_engram_project_key(user_id: int, project_id: int | None = None) -> str:
    """Aísla la memoria de Engram por usuario."""
    prefix = os.getenv("ENGRAM_PROJECT", "arch-agent")
    return f"{prefix}-user-{user_id}"


# --- Phases ----------------------------------------------------------------

PHASES = ["requerimientos", "propuesta", "refinamiento", "revision"]
PHASE_LABELS = {
    "requerimientos": "Requerimientos",
    "propuesta": "Propuesta",
    "refinamiento": "Refinamiento",
    "revision": "Revisión",
}


# --- Formatting -------------------------------------------------------------

def format_local(dt: datetime | None) -> str:
    """Format a UTC datetime as local Bogotá time string."""
    if dt is None:
        return "sin fecha"
    dt_utc = dt.replace(tzinfo=timezone.utc)
    dt_local = dt_utc.astimezone(BOGOTA_TZ)
    return dt_local.strftime("%d/%m/%Y %I:%M %p")


# --- Projects --------------------------------------------------------------

def get_projects_for_user(user_id: int):
    db = SessionLocal()
    try:
        return db.query(Project).filter(
            Project.user_id == user_id
        ).order_by(Project.updated_at.desc()).all()
    finally:
        db.close()


def get_project_name(user_id: int, project_id: int | None) -> str:
    """Nombre legible del proyecto para mostrar en mensajes; 'sin asignar' si no hay."""
    if project_id is None:
        return "sin asignar"
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        return project.name if project else "sin asignar"
    finally:
        db.close()


def create_project(
    user_id: int,
    name: str,
    description: str | None = None,
    current_phase: str = "requerimientos",
):
    name = name.strip()
    if not name:
        raise ValidationError("El nombre del proyecto no puede estar vacío.")
    db = SessionLocal()
    try:
        existing = db.query(Project).filter(
            Project.user_id == user_id, Project.name == name
        ).first()
        if existing:
            raise ValidationError(f"Ya tienes un proyecto llamado '{name}'.")
        project = Project(
            user_id=user_id,
            name=name,
            description=description,
            current_phase=current_phase,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def delete_project(user_id: int, project_id: int):
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            raise ValidationError(
                "No se encontró ese proyecto, o no te pertenece."
            )
        db.delete(project)
        db.commit()
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_project(user_id: int, project_id: int) -> Project | None:
    db = SessionLocal()
    try:
        return db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
    finally:
        db.close()


def advance_phase(user_id: int, project_id: int) -> Project:
    """Avanza el proyecto a la siguiente fase de PHASES, solo si phase_ready es True."""
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            raise ValidationError(
                "No se encontró ese proyecto, o no te pertenece."
            )
        if not project.phase_ready:
            label = PHASE_LABELS.get(
                project.current_phase, project.current_phase or "sin asignar"
            )
            raise ValidationError(
                f"La fase '{label}' todavía no está completa. No puedes avanzar aún."
            )
        idx = (
            PHASES.index(project.current_phase)
            if project.current_phase in PHASES
            else -1
        )
        if idx == -1:
            raise ValidationError(
                "Este proyecto tiene una fase no reconocida; revísala manualmente."
            )
        if idx == len(PHASES) - 1:
            raise ValidationError("Ya estás en la última fase.")
        project.current_phase = PHASES[idx + 1]
        project.phase_ready = False
        db.commit()
        db.refresh(project)
        return project
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def mark_phase_ready(user_id: int, project_id: int) -> Project:
    """
    Marca la fase actual como lista para avanzar.

    TEMPORAL (dev): cuando F08 conecte el agente LangChain, esta misma
    función será llamada por el agente cuando determine que ya se cumplió
    todo lo necesario de la fase.
    """
    db = SessionLocal()
    try:
        project = db.query(Project).filter(
            Project.id == project_id, Project.user_id == user_id
        ).first()
        if project is None:
            raise ValidationError(
                "No se encontró ese proyecto, o no te pertenece."
            )
        project.phase_ready = True
        db.commit()
        db.refresh(project)
        return project
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
