import os
from pathlib import Path

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
from app.llm.config_form import render_config_form_if_needed, render_sidebar_settings  # noqa: F401

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
    """Hook al iniciar chat: verifica config LLM y muestra form si es necesario."""
    user = cl.user_session.get("user")
    if not user:
        await cl.Message(content="⚠️ No hay usuario autenticado.").send()
        return

    user_id = user.metadata["user_id"]

    # Verificar si tiene config LLM (HU12)
    config_ok = await render_config_form_if_needed(user_id)
    if not config_ok:
        # Ya se mostró el form (paso 1/3 pide URL)
        return

    # Si tiene config, mostrar bienvenida
    await cl.Message(
        content=f"¡Bienvenida {user.identifier}! Sesión iniciada correctamente.\n\n"
        f"Tu LLM está configurado. Si querés cambiarlo, usá el botón:",
        actions=[await render_sidebar_settings(user_id)],
    ).send()

@cl.on_chat_end
async def on_end():
    """Hook al cerrar chat: limpia cache de modelo en memoria."""
    from app.core.llm_loader import clear_session_cache
    user = cl.user_session.get("user")
    if user:
        user_id = user.metadata.get("user_id")
        if user_id:
            clear_session_cache(user_id)
    pass