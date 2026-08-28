import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.api.dependencies import JWT_REVOKED, get_current_user
from app.auth.register import register_user as _register_user
from app.auth.validators import ValidationError
from app.core.database import SessionLocal
from app.core.jwt import create_access_token
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- Request/Response models -------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str  # username or email


class TokenResponse(BaseModel):
    user_id: int
    username: str
    token: str


class LogoutResponse(BaseModel):
    message: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        from_attributes = True


# --- Helpers -----------------------------------------------------------------


def _get_user_by_login(login: str) -> User | None:
    """Search by username or email."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            (User.username == login) | (User.email == login)
        ).first()
        return user
    finally:
        db.close()


# --- Routes ------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    """
    Register a new user account.
    Returns a JWT token on success.
    """
    try:
        user = _register_user(body.username, body.email, body.password)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    token = create_access_token(user.id, user.username)
    return TokenResponse(user_id=user.id, username=user.username, token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    """
    Authenticate with username or email + password.
    Returns a JWT token on success.
    """
    user = _get_user_by_login(body.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(user.id, user.username)
    return TokenResponse(user_id=user.id, username=user.username, token=token)


@router.post("/logout", response_model=LogoutResponse)
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Revoke the current JWT by adding its jti to the revocation list.
    Subsequent requests with this token will receive 401.
    """
    jti = current_user.get("jti")
    if jti:
        JWT_REVOKED.add(jti)
    return LogoutResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def me(current_user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == current_user["user_id"]).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return UserResponse.model_validate(user)
    finally:
        db.close()
