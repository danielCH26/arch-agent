import os
import logging
from pathlib import Path
from uuid import uuid4

import bcrypt
import chainlit as cl
from dotenv import load_dotenv

# Cargar variables del .env al inicio (antes que nada)
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

from app.core.database import SessionLocal
from app.models.user import User
from app.auth.register import register_user
from app.auth.validators import ValidationError
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
        # Ya se mostró el form (paso 1/3 pide URL)
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


@cl.on_message
async def handle_message(message: cl.Message):
    if message.content.strip().lower().startswith("/set_fase "):
        fase = message.content.strip().split(" ", 1)[1]
        user = cl.user_session.get("user")
        user_id = user.metadata["user_id"]
        cl.user_session.set("active_phase", fase)
        project_id = cl.user_session.get("project_id")
        engram_session_id = cl.user_session.get("engram_session_id")
        engram_project_key = cl.user_session.get("engram_project_key") or get_engram_project_key(user_id, project_id)
        summary = f"Proyecto activo: {project_id or 'sin asignar'}. Fase activa: {fase}."

        # Se persiste aquí y no solo en on_chat_end: recargar/cerrar una
        # pestaña puede interrumpir el callback de cierre de Chainlit.
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

    await handle_config_flow(message)
