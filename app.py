import bcrypt
import chainlit as cl
from zoneinfo import ZoneInfo
from app.core.database import SessionLocal
from app.models.user import User
from app.models.project import Project
from app.auth.register import register_user
from app.auth.validators import ValidationError

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
    await cl.Message(content="¡Bienvenida! Sesión iniciada correctamente.").send()


@cl.on_chat_end
async def on_end():
    # Punto de enganche para "logout funcional": aquí se limpia lo que
    # el resto de HUs vaya guardando en cl.user_session (ver HU2).
    pass


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
    cl.user_session.set("project_id", project_id)
    await cl.Message(content=f"Proyecto seleccionado (id {project_id}). Continuemos donde lo dejaste.").send()

@cl.on_message
async def handle_message(message: cl.Message):
    content = message.content.strip()
    lower = content.lower()
    user = cl.user_session.get("user")

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