import bcrypt
import chainlit as cl
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.register import register_user
from app.auth.validators import ValidationError
from app.models.project import Project
from zoneinfo import ZoneInfo

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
def get_projects_for_user(user_id: int):
    db = SessionLocal()
    try:
        return db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).all()
    finally:
        db.close()

@cl.on_message
async def handle_list_projects_command(message: cl.Message):
    if message.content.strip().lower() != "/proyectos":
        return
    user = cl.user_session.get("user")
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

@cl.action_callback("select_project")
async def on_project_selected(action: cl.Action):
    project_id = action.payload["project_id"]
    cl.user_session.set("project_id", project_id)
    await cl.Message(content=f"Proyecto seleccionado (id {project_id}). Continuemos donde lo dejaste.").send()

BOGOTA_TZ = ZoneInfo("America/Bogota")

def format_local(dt):
    if dt is None:
        return "sin fecha"
    dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))
    dt_local = dt_utc.astimezone(BOGOTA_TZ)
    return dt_local.strftime('%d/%m/%Y %I:%M %p')