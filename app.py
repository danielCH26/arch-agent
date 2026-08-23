import bcrypt
import chainlit as cl
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.register import register_user
from app.auth.validators import ValidationError

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