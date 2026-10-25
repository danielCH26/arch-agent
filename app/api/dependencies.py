from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.jwt import JWTError, verify_token

# In-memory revoked token set. Tokens are added on logout with their jti.
# For production at scale, swap this for a Redis set.
JWT_REVOKED: set[str] = set()

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency that validates the Bearer JWT and returns the payload.

    Raises 401 if:
    - Token is missing or malformed
    - Token has expired
    - Token has been revoked (logout)
    """
    token = credentials.credentials
    try:
        payload = verify_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check revocation list
    jti: str | None = payload.get("jti")
    if jti and jti in JWT_REVOKED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing user id",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"user_id": int(user_id), "username": payload.get("username"), "jti": jti}
