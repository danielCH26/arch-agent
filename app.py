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
from app.auth.profile import get_profile, update_profile, change_password
from app.core.session_store import save_session_state, load_session_state
from app.core.engram_client import EngramClient, EngramError
from app.llm.config_form import (
    handle_config_flow,
    render_config_form_if_needed,
    render_sidebar_settings,
    set_on_config_complete,
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


def normalize_phase(raw: str) -> str:
    """Limpia lo que escribe el usuario como fase: quita espacios y '/' o '#' sueltos
    al inicio (por si lo escribe como si fuera un comando), y baja a minúsculas."""
    fase = raw.strip()
    fase = fase.lstrip("/#").strip()
    return fase.lower()


PASSWORD_RULES_TEXT = (
    "**La contraseña debe cumplir:**\n"
    "- Mínimo 8 caracteres\n"
    "- Al menos 1 letra mayúscula\n"
    "- Al menos 1 número\n"
    "- Al menos 1 carácter especial (ej: ! @ # $ % &)"
)


# --- Menú principal -----------------------------------------------------

def main_menu_actions():
    return [
        cl.Action(name="menu_proyectos", payload={}, label="📁 Mis proyectos"),
        cl.Action(name="menu_crear_proyecto", payload={}, label="➕ Crear proyecto"),
        cl.Action(name="menu_eliminar_proyecto", payload={}, label="🗑️ Eliminar proyecto"),
        cl.Action(name="menu_set_fase", payload={}, label="🔄 Cambiar fase activa"),
        cl.Action(name="menu_perfil", payload={}, label="👤 Ver perfil"),
        cl.Action(name="menu_editar_perfil", payload={}, label="✏️ Editar perfil"),
        cl.Action(name="menu_cambiar_password", payload={}, label="🔒 Cambiar contraseña"),
        cl.Action(name="menu_llm_config", payload={}, label="⚙️ Configurar LLM"),
    ]


async def send_main_menu(text: str = "¿Qué quieres hacer?"):
    cl.user_session.set("pending_flow", None)  # cualquier flujo de texto pendiente se cancela
    await cl.Message(content=text, actions=main_menu_actions()).send()


# Cuando config_form.py termina de guardar la configuración de LLM (ya sea
# porque el usuario escribió el modelo o hizo clic en un botón), nos avisa
# llamando a esta misma función, así el menú aparece sin que el usuario
# tenga que escribir nada.
set_on_config_complete(send_main_menu)


def start_flow(flow_type: str, first_step: str, data: dict | None = None):
    """Guarda en la sesión qué flujo de texto libre está esperando el próximo mensaje."""
    cl.user_session.set(
        "pending_flow",
        {"type": flow_type, "step": first_step, "data": data or {}},
    )


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

    config_ok = await render_config_form_if_needed(user_id)
    if not config_ok:
        return

    state = load_session_state(user_id)
    project_id = state["project_id"] if state else None
    project_key = get_engram_project_key(user_id, project_id)
    engram_session_id = str(uuid4())
    cl.user_session.set("engram_session_id", engram_session_id)
    cl.user_session.set("engram_project_key", project_key)
    cl.user_session.set("pending_flow", None)

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
        project_name = get_project_name(user_id, state["project_id"])
        await send_main_menu(
            "Bienvenida de vuelta. "
            f"Proyecto activo: {project_name}, "
            f"fase: '{state['active_phase'] or 'sin asignar'}'.\n\n¿Qué quieres hacer?"
        )
    else:
        await send_main_menu(
            f"¡Bienvenida {user.identifier}! Sesión iniciada correctamente.\n\n¿Qué quieres hacer?"
        )



@cl.on_chat_end
async def on_end():
    # Punto de enganche para "logout funcional": aquí se limpia lo que
    # el resto de HUs vaya guardando en cl.user_session (ver HU2).
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


@cl.action_callback("menu_proyectos")
async def on_menu_proyectos(action: cl.Action):
    user = cl.user_session.get("user")
    projects = get_projects_for_user(user.metadata["user_id"])
    if not projects:
        await cl.Message(content="Todavía no tienes proyectos.").send()
        await send_main_menu()
        return
    actions = [
        cl.Action(
            name="select_project",
            payload={"project_id": p.id},
            label=f"{p.name} — última actividad: {format_local(p.updated_at)}",
        )
        for p in projects
    ]
    actions.append(cl.Action(name="menu_volver", payload={}, label="⬅️ Volver al menú"))
    await cl.Message(content="Elige un proyecto para continuar:", actions=actions).send()


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
    project_name = get_project_name(user.metadata["user_id"], project_id) if user else project_id
    await cl.Message(content=f"Proyecto seleccionado: {project_name}. Continuemos donde lo dejaste.").send()
    await send_main_menu()


@cl.action_callback("menu_crear_proyecto")
async def on_menu_crear_proyecto(action: cl.Action):
    start_flow("crear_proyecto", "name")
    await cl.Message(content="Nombre del nuevo proyecto (o 'cancelar'):").send()


@cl.action_callback("menu_eliminar_proyecto")
async def on_menu_eliminar_proyecto(action: cl.Action):
    user = cl.user_session.get("user")
    projects = get_projects_for_user(user.metadata["user_id"])
    if not projects:
        await cl.Message(content="Todavia no tienes proyectos para eliminar.").send()
        await send_main_menu()
        return

    actions = [
        cl.Action(
            name="request_delete_project",
            payload={"project_id": p.id, "project_name": p.name},
            label=f"Eliminar {p.name}",
        )
        for p in projects
    ]
    actions.append(cl.Action(name="menu_volver", payload={}, label="⬅️ Volver al menú"))
    await cl.Message(content="Elige el proyecto que quieres eliminar:", actions=actions).send()


@cl.action_callback("request_delete_project")
async def on_project_delete_requested(action: cl.Action):
    await cl.Message(
        content=f"Seguro que quieres eliminar '{action.payload['project_name']}'?",
        actions=[
            cl.Action(name="confirm_delete_project", payload=action.payload, label="Si, eliminar"),
            cl.Action(name="cancel_delete_project", payload={}, label="Cancelar"),
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
    await send_main_menu()


@cl.action_callback("cancel_delete_project")
async def on_project_delete_cancelled(action: cl.Action):
    await cl.Message(content="Eliminacion cancelada.").send()
    await send_main_menu()


# --- Fase activa ---------------------------------------------------------

@cl.action_callback("menu_set_fase")
async def on_menu_set_fase(action: cl.Action):
    start_flow("set_fase", "fase")
    await cl.Message(content="¿Cuál es la nueva fase activa? (o 'cancelar'):").send()


# --- Perfil ----------------------------------------------------------------

@cl.action_callback("menu_perfil")
async def on_menu_perfil(action: cl.Action):
    user = cl.user_session.get("user")
    profile = get_profile(user.metadata["user_id"])
    await cl.Message(
        content=f"Tu perfil:\n- Username: {profile['username']}\n- Email: {profile['email']}"
    ).send()
    await send_main_menu()


@cl.action_callback("menu_editar_perfil")
async def on_menu_editar_perfil(action: cl.Action):
    start_flow("editar_perfil", "username")
    await cl.Message(content="Nuevo username (escribe - si no quieres cambiarlo, o 'cancelar'):").send()


@cl.action_callback("menu_cambiar_password")
async def on_menu_cambiar_password(action: cl.Action):
    start_flow("cambiar_password", "current")
    await cl.Message(
        content=f"{PASSWORD_RULES_TEXT}\n\nContraseña actual (o 'cancelar'):"
    ).send()


# --- Config LLM ------------------------------------------------------------

@cl.action_callback("menu_llm_config")
async def on_menu_llm_config(action: cl.Action):
    user_id = cl.user_session.get("user").metadata["user_id"]
    await cl.Message(
        content="Configura tu LLM:",
        actions=[await render_sidebar_settings(user_id)],
    ).send()


# --- Navegación genérica -----------------------------------------------

@cl.action_callback("menu_volver")
async def on_menu_volver(action: cl.Action):
    await send_main_menu()


# --- Manejo de los flujos de texto libre (reemplaza a AskUserMessage) -----

async def _handle_pending_flow(flow: dict, text: str, user):
    user_id = user.metadata["user_id"]
    flow_type = flow["type"]
    step = flow["step"]
    data = flow["data"]

    if flow_type == "crear_proyecto":
        if step == "name":
            data["name"] = text
            start_flow("crear_proyecto", "description", data)
            await cl.Message(content="Descripción (escribe - si no quieres agregar una):").send()
            return
        if step == "description":
            description = None if text in ("", "-") else text
            try:
                project = create_project(user_id, data["name"], description)
                await cl.Message(content=f"Proyecto '{project.name}' creado (id {project.id}).").send()
            except ValidationError as e:
                await cl.Message(content=f"No se pudo crear: {e}").send()
            await send_main_menu()
            return

    if flow_type == "set_fase":
        fase = normalize_phase(text)
        if not fase:
            await cl.Message(content="No se registró ninguna fase.").send()
            await send_main_menu()
            return
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
                    engram_session_id, engram_project_key, "Fase de flujo actualizada", summary
                )
            except EngramError as exc:
                logger.warning("No se pudo guardar la fase en Engram para el usuario %s: %s", user_id, exc)
        await cl.Message(content=f"Fase actualizada a: {fase}").send()
        await send_main_menu()
        return

    if flow_type == "editar_perfil":
        if step == "username":
            data["username"] = None if text in ("", "-") else text
            start_flow("editar_perfil", "email", data)
            await cl.Message(content="Nuevo email (escribe - si no quieres cambiarlo, o 'cancelar'):").send()
            return
        if step == "email":
            data["email"] = None if text in ("", "-") else text
            try:
                updated = update_profile(user_id, email=data["email"], username=data["username"])
                await cl.Message(
                    content=(
                        "Perfil actualizado:\n"
                        f"- Username: {updated['username']}\n"
                        f"- Email: {updated['email']}"
                    )
                ).send()
                await send_main_menu()
            except ValidationError as e:
                # Reintenta solo el email, sin perder el username ya escrito.
                start_flow("editar_perfil", "email", {"username": data["username"]})
                await cl.Message(
                    content=f"❌ No se pudo actualizar: {e}\n\nNuevo email (o 'cancelar'):"
                ).send()
            return

    if flow_type == "cambiar_password":
        if step == "current":
            data["current"] = text
            start_flow("cambiar_password", "new", data)
            await cl.Message(
                content=f"{PASSWORD_RULES_TEXT}\n\nNueva contraseña (o 'cancelar'):"
            ).send()
            return
        if step == "new":
            try:
                change_password(user_id, data["current"], text)
                await cl.Message(content="Contraseña actualizada correctamente.").send()
                await send_main_menu()
            except ValidationError as e:
                # Reintenta pidiendo de nuevo la contraseña actual, ya que el error
                # puede venir de ahí (contraseña actual incorrecta) o de la nueva.
                start_flow("cambiar_password", "current")
                await cl.Message(
                    content=(
                        f"❌ No se pudo cambiar: {e}\n\n"
                        f"{PASSWORD_RULES_TEXT}\n\nContraseña actual (o 'cancelar'):"
                    )
                ).send()
            return


@cl.on_message
async def handle_message(message: cl.Message):
    user = cl.user_session.get("user")
    flow = cl.user_session.get("pending_flow")
    text = message.content.strip()

    if flow and text.lower() in ("cancelar", "/cancelar"):
        await cl.Message(content="Operación cancelada.").send()
        await send_main_menu()
        return

    if flow:
        await _handle_pending_flow(flow, text, user)
        return

    # Sin flujo pendiente: es texto suelto, probablemente para el flujo de config LLM.
    await handle_config_flow(message)