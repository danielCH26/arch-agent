import bcrypt
import chainlit as cl
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.register import register_user
from app.auth.validators import ValidationError
from app.llm.config_form import render_config_form_if_needed, render_sidebar_settings
from app.core.session_store import save_session_state, load_session_state

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
        return  # Se mostró el form, esperar a que el usuario complete

    # Si tiene config, mostrar bienvenida + botón en sidebar
    await cl.Message(
        content=f"¡Bienvenida {user.identifier}! Sesión iniciada correctamente."
    ).send()
    await render_sidebar_settings(user_id)
    user = cl.user_session.get("user")
    user_id = user.metadata["user_id"]

    state = load_session_state(user_id)
    if state and state["project_id"]:
        cl.user_session.set("project_id", state["project_id"])
        cl.user_session.set("active_phase", state["active_phase"])
        await cl.Message(
            content=f"Bienvenida de vuelta. Proyecto activo: {state['project_id']}, fase: '{state['active_phase']}'."
        ).send()
    else:
        await cl.Message(content="¡Bienvenida! Todavía no tienes una sesión activa.").send()

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
    user = cl.user_session.get("user")
    if not user:
        return
    user_id = user.metadata["user_id"]
    save_session_state(
        user_id,
        project_id=cl.user_session.get("project_id"),
        active_phase=cl.user_session.get("active_phase"),
    )
@cl.on_message
async def handle_test_phase_command(message: cl.Message):
    if message.content.strip().lower().startswith("/set_fase "):
        fase = message.content.strip().split(" ", 1)[1]
        user = cl.user_session.get("user")
        cl.user_session.set("active_phase", fase)
        cl.user_session.set("project_id", 1)  
        await cl.Message(content=f"Fase simulada como: {fase}").send()