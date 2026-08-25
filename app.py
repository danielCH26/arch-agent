import os
import logging
from pathlib import Path
from uuid import uuid4

import bcrypt
import chainlit as cl
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Cargar variables del .env al inicio (antes que nada)
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

from app.core.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.auth.register import register_user
from app.auth.validators import ValidationError
from app.auth.profile import get_profile, update_profile
from app.core.session_store import save_session_state, load_session_state
from app.core.engram_client import EngramClient, EngramError
from app.llm.config_form import (
    handle_config_flow,
    render_config_form_if_needed,
    render_sidebar_settings,
)

logger = logging.getLogger(__name__)


def get_engram_project_key(user_id: int, project_id: int | None = None) -> str:
    """Aísla la memoria de Engram por usuario; el resumen conserva el proyecto activo."""
    prefix = os.getenv("ENGRAM_PROJECT", "arch-agent")
    return f"{prefix}-user-{user_id}"


BOGOTA_TZ = ZoneInfo("America/Bogota")


def format_local(dt):
    if dt is None:
        return "sin fecha"
    dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
    dt_local = dt_utc.astimezone(BOGOTA_TZ)
    return dt_local.strftime('%d/%m/%Y %I:%M %p')


# --- Auth (HU1) -------------------------------------------------------------

def get_user_by_login(login: str):
    """Busca por username o por email, para que el login funcione con cualquiera de los dos."""
    db = SessionLocal()
    try:
        return db.query(User).filter(
            (User.username == login) | (User.email == login)
        ).first()
    finally:
        db.close()


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    user = get_user_by_login(username)
    if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return cl.User(identifier=user.username, metadata={"user_id": user.id})
    return None


@cl.on_chat_start
async def start():
    user = cl.user_session.get("user")
    user_id = user.metadata["user_id"]

    # Verificar si tiene config LLM (HU12)
    config_ok = await render_config_form_if_needed(user_id)
    if not config_ok:
        return

    state = load_session_state(user_id)
    project_id = state["project_id"] if state else None
    project_key = get_engram_project_key(user_id, project_id)
    engram_session_id = str(uuid4())
    cl.user_session.set("engram_session_id", engram_session_id)
    cl.user_session.set("engram_project_key", project_key)

    try:
        engram = EngramClient()
        engram.create_session(engram_session_id, project_key, os.getcwd())
        cl.user_session.set("engram_context", engram.get_context(project_key))
    except EngramError as exc:
        logger.warning("No se pudo recuperar la memoria de Engram para el usuario %s: %s", user_id, exc)
        cl.user_session.set("engram_context", "")

    if state and (state["project_id"] is not None or state["active_phase"] is not None):
        cl.user_session.set("project_id", state["project_id"])
        cl.user_session.set("active_phase", state["active_phase"])
        await cl.Message(
            content=(
                "Bienvenida de vuelta. "
                f"Proyecto activo: {state['project_id'] or 'sin asignar'}, "
                f"fase: '{state['active_phase'] or 'sin asignar'}'."
            )
        ).send()
    else:
        await cl.Message(
            content=f"¡Bienvenida {user.identifier}! Sesión iniciada correctamente.\n\n"
            f"Tu LLM está configurado. Si querés cambiarlo, usá el botón:",
            actions=[await render_sidebar_settings(user_id)],
        ).send()


@cl.on_chat_end
async def on_end():
    user = cl.user_session.get("user")
    if not user:
        return
    user_id = user.metadata["user_id"]
    project_id = cl.user_session.get("project_id")
    active_phase = cl.user_session.get("active_phase")
    engram_session_id = cl.user_session.get("engram_session_id")
    engram_project_key = cl.user_session.get("engram_project_key") or get_engram_project_key(user_id, project_id)
    summary = f"Proyecto activo: {project_id or 'sin asignar'}. Fase activa: {active_phase or 'sin asignar'}."

    engram_state = {
        "engram_session_id": engram_session_id,
        "project_key": engram_project_key,
    }
    save_session_state(
        user_id,
        project_id=project_id,
        active_phase=active_phase,
        engram_state=engram_state,
    )
    if not engram_session_id:
        return
    try:
        engram = EngramClient()
        engram.save_observation(engram_session_id, engram_project_key, "Estado de sesión guardado", summary)
        engram.end_session(engram_session_id, summary)
    except EngramError as exc:
        logger.warning("No se pudo guardar la memoria de Engram para el usuario %s: %s", user_id, exc)


# --- Proyectos (HU3 + creación/eliminación) ---------------------------------

def get_projects_for_user(user_id: int):
    db = SessionLocal()
    try:
        return db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).all()
    finally:
        db.close()


def create_project(user_id: int, name: str, description: str = None, current_phase: str = "elicitación"):
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

        project = Project(user_id=user_id, name=name, description=description, current_phase=current_phase)
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
            raise ValidationError("No se encontró ese proyecto, o no te pertenece.")
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


@cl.action_callback("select_project")
async def on_project_selected(action: cl.Action):
    project_id = action.payload["project_id"]
    user = cl.user_session.get("user")
    cl.user_session.set("project_id", project_id)
    if user:
        save_session_state(
            user.metadata["user_id"],
            project_id=project_id,
            active_phase=cl.user_session.get("active_phase"),
        )
    await cl.Message(content=f"Proyecto seleccionado (id {project_id}). Continuemos donde lo dejaste.").send()


@cl.action_callback("request_delete_project")
async def on_project_delete_requested(action: cl.Action):
    await cl.Message(
        content=f"Seguro que quieres eliminar '{action.payload['project_name']}'?",
        actions=[
            cl.Action(
                name="confirm_delete_project",
                payload=action.payload,
                label="Si, eliminar",
            ),
            cl.Action(
                name="cancel_delete_project",
                payload={},
                label="Cancelar",
            ),
        ],
    ).send()


@cl.action_callback("confirm_delete_project")
async def on_project_delete_confirmed(action: cl.Action):
    user = cl.user_session.get("user")
    if not user:
        await cl.Message(content="No hay una sesion activa para eliminar proyectos.").send()
        return

    project_id = action.payload["project_id"]
    try:
        delete_project(user.metadata["user_id"], project_id)
        if cl.user_session.get("project_id") == project_id:
            cl.user_session.set("project_id", None)
        await cl.Message(content=f"Proyecto eliminado: {action.payload['project_name']}.").send()
    except ValidationError as e:
        await cl.Message(content=f"No se pudo eliminar: {e}").send()


@cl.action_callback("cancel_delete_project")
async def on_project_delete_cancelled(action: cl.Action):
    await cl.Message(content="Eliminacion cancelada.").send()


# --- Mensajes -----------------------------------------------------------

@cl.on_message
async def handle_message(message: cl.Message):
    content = message.content.strip()
    lower = content.lower()
    user = cl.user_session.get("user")

    # --- Perfil (HU4) ---
    if lower == "/perfil":
        profile = get_profile(user.metadata["user_id"])
        await cl.Message(
            content=f"Tu perfil:\n- Username: {profile['username']}\n- Email: {profile['email']}"
        ).send()
        return

    if lower == "/editar_perfil":
        username_msg = await cl.AskUserMessage(
            content="Nuevo username (escribe - si no quieres cambiarlo):"
        ).send()
        email_msg = await cl.AskUserMessage(
            content="Nuevo email (escribe - si no quieres cambiarlo):"
        ).send()

        raw_username = username_msg["output"].strip()
        raw_email = email_msg["output"].strip()

        new_username = None if raw_username in ("", "-") else raw_username
        new_email = None if raw_email in ("", "-") else raw_email

        try:
            updated = update_profile(
                user.metadata["user_id"],
                email=new_email,
                username=new_username,
            )
            await cl.Message(
                content=(
                    "Perfil actualizado:\n"
                    f"- Username: {updated['username']}\n"
                    f"- Email: {updated['email']}"
                )
            ).send()
        except ValidationError as e:
            await cl.Message(
                content=f"No se pudo actualizar: {e}\n\nEscribe /editar_perfil para volver a intentarlo."
            ).send()
        return

    if lower.startswith("/set_fase "):
        fase = content.split(" ", 1)[1]
        user_id = user.metadata["user_id"]
        cl.user_session.set("active_phase", fase)
        project_id = cl.user_session.get("project_id")
        engram_session_id = cl.user_session.get("engram_session_id")
        engram_project_key = cl.user_session.get("engram_project_key") or get_engram_project_key(user_id, project_id)
        summary = f"Proyecto activo: {project_id or 'sin asignar'}. Fase activa: {fase}."

        save_session_state(
            user_id,
            project_id=project_id,
            active_phase=fase,
            engram_state={"engram_session_id": engram_session_id, "project_key": engram_project_key},
        )
        if engram_session_id:
            try:
                EngramClient().save_observation(
                    engram_session_id,
                    engram_project_key,
                    "Fase de flujo actualizada",
                    summary,
                )
            except EngramError as exc:
                logger.warning("No se pudo guardar la fase en Engram para el usuario %s: %s", user_id, exc)
        await cl.Message(content=f"Fase simulada como: {fase}").send()
        return

    if lower == "/proyectos":
        projects = get_projects_for_user(user.metadata["user_id"])
        if not projects:
            await cl.Message(content="Todavía no tienes proyectos.").send()
            return
        actions = [
            cl.Action(
                name="select_project",
                payload={"project_id": p.id},
                label=f"{p.name} — última actividad: {format_local(p.updated_at)}",
            )
            for p in projects
        ]
        await cl.Message(content="Elige un proyecto para continuar:", actions=actions).send()
        return

    if lower == "/crear_proyecto":
        name_msg = await cl.AskUserMessage(content="Nombre del nuevo proyecto:").send()
        desc_msg = await cl.AskUserMessage(content="Descripción (escribe - si no quieres agregar una):").send()

        name = name_msg["output"].strip()
        raw_desc = desc_msg["output"].strip()
        description = None if raw_desc in ("", "-") else raw_desc

        try:
            project = create_project(user.metadata["user_id"], name, description)
            await cl.Message(
                content=f"Proyecto '{project.name}' creado (id {project.id}). Escribe /proyectos para verlo en la lista."
            ).send()
        except ValidationError as e:
            await cl.Message(content=f"No se pudo crear: {e}\n\nEscribe /crear_proyecto para volver a intentarlo.").send()
        return

    if lower == "/eliminar_proyecto":
        projects = get_projects_for_user(user.metadata["user_id"])
        if not projects:
            await cl.Message(content="Todavia no tienes proyectos para eliminar.").send()
            return

        actions = [
            cl.Action(
                name="request_delete_project",
                payload={"project_id": p.id, "project_name": p.name},
                label=f"Eliminar {p.name}",
            )
            for p in projects
        ]
        await cl.Message(content="Elige el proyecto que quieres eliminar:", actions=actions).send()
        return

    if lower.startswith("/eliminar_proyecto "):
        try:
            project_id = int(content.split(" ", 1)[1])
        except ValueError:
            await cl.Message(content="Uso: /eliminar_proyecto <id>. Escribe /proyectos para ver los ids.").send()
            return

        try:
            delete_project(user.metadata["user_id"], project_id)
            await cl.Message(content=f"Proyecto {project_id} eliminado.").send()
        except ValidationError as e:
            await cl.Message(content=f"No se pudo eliminar: {e}").send()
        return

    await handle_config_flow(message)