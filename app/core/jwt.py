import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from dotenv import load_dotenv

load_dotenv()

ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))


class JWTError(Exception):
    pass


def get_secret_key() -> str:
    key = os.getenv("JWT_SECRET_KEY", "")
    if not key:
        raise JWTError("JWT_SECRET_KEY environment variable is not set")
    return key


def create_access_token(
    user_id: int,
    username: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token."""
    secret = get_secret_key()
    expires = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=EXPIRES_MINUTES)
    )
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expires,
        "iat": datetime.now(timezone.utc),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    """Verify and decode a JWT. Raises JWTError on failure."""
    secret = get_secret_key()
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise JWTError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise JWTError(f"Invalid token: {e}")
