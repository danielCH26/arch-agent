from sqlalchemy.exc import IntegrityError
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.validators import validate_username, validate_email_input, ValidationError
import bcrypt
from app.auth.validators import validate_password

def get_profile(user_id: int):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise ValidationError("Usuario no encontrado.")
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() + "Z" if user.created_at else None,
        }
    finally:
        db.close()

def update_profile(user_id: int, email: str = None, username: str = None):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise ValidationError("Usuario no encontrado.")

        if username:
            username = validate_username(username)
            conflict = db.query(User).filter(User.username == username, User.id != user_id).first()
            if conflict:
                raise ValidationError("Ese username ya está en uso por otra cuenta.")
            user.username = username

        if email:
            email = validate_email_input(email)
            conflict = db.query(User).filter(User.email == email, User.id != user_id).first()
            if conflict:
                raise ValidationError("Ese email ya está en uso por otra cuenta.")
            user.email = email

        db.commit()
        db.refresh(user)
        return {"username": user.username, "email": user.email}
    except IntegrityError:
        db.rollback()
        raise ValidationError("Ese username o email ya está en uso por otra cuenta.")
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def change_password(user_id: int, current_password: str, new_password: str):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise ValidationError("Usuario no encontrado.")
        if not bcrypt.checkpw(current_password.encode(), user.password_hash.encode()):
            raise ValidationError("La contraseña actual no es correcta.")
        validate_password(new_password)
        user.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        db.commit()
    except ValidationError:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()