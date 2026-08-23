import re
from email_validator import validate_email, EmailNotValidError

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,100}$")

class ValidationError(Exception):
    pass

def validate_username(username: str) -> str:
    if not username or not USERNAME_RE.match(username):
        raise ValidationError(
            "El username debe tener entre 3 y 100 caracteres: letras, números o guion bajo."
        )
    return username

def validate_email_input(email: str) -> str:
    try:
        result = validate_email(email, check_deliverability=False)
        return result.normalized
    except EmailNotValidError:
        raise ValidationError("El email no tiene un formato válido.")

def validate_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValidationError("La contraseña debe tener al menos 8 caracteres.")
    return password