import bcrypt
import chainlit as cl
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.register import register_user
from app.auth.validators import ValidationError
from app.auth.profile import get_profile, update_profile

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
    await cl.Message(content="¡Bienvenida! Sesión iniciada correctamente.").send()

@cl.on_chat_end
async def on_end():
    # Punto de enganche para "logout funcional": aquí se limpia lo que
    # el resto de HUs vaya guardando en cl.user_session (ver HU2).
    pass


@cl.on_message
async def handle_profile_commands(message: cl.Message):
    content = message.content.strip()

    if content.lower() == "/perfil":
        user = cl.user_session.get("user")
        profile = get_profile(user.metadata["user_id"])
        await cl.Message(content=f"Tu perfil:\n- Username: {profile['username']}\n- Email: {profile['email']}").send()
        return

    if content.lower() == "/editar_perfil":
        user = cl.user_session.get("user")
        username_msg = await cl.AskUserMessage(content="Nuevo username (escribe - si no quieres cambiarlo):").send()
        email_msg = await cl.AskUserMessage(content="Nuevo email (escribe - si no quieres cambiarlo):").send()

        raw_username = username_msg["output"].strip()
        raw_email = email_msg["output"].strip()

        new_username = None if raw_username in ("", "-") else raw_username
        new_email = None if raw_email in ("", "-") else raw_email

        try:
            updated = update_profile(user.metadata["user_id"], email=new_email, username=new_username)
            await cl.Message(
                content=f"Perfil actualizado:\n- Username: {updated['username']}\n- Email: {updated['email']}"
            ).send()
        except ValidationError as e:
            await cl.Message(content=f"No se pudo actualizar: {e}\n\nEscribe /editar_perfil para volver a intentarlo.").send()
        return