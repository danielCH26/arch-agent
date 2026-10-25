import bcrypt
from sqlalchemy.exc import IntegrityError
from app.core.database import SessionLocal
from app.models.user import User
from app.auth.validators import validate_username, validate_email_input, validate_password, ValidationError

def register_user(username: str, email: str, password: str) -> User:
    username = validate_username(username)
    email = validate_email_input(email)
    password = validate_password(password)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    db = SessionLocal()
    try:
        user = User(username=username, email=email, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise ValidationError("Ese username o email ya está registrado.")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()