from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.api.dependencies import get_current_user
from app.auth.profile import change_password, get_profile, update_profile
from app.auth.validators import ValidationError

router = APIRouter(prefix="/api/users", tags=["users"])


# --- Request/Response models -------------------------------------------------


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# --- Routes -----------------------------------------------------------------


@router.get("/me", response_model=UserOut)
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Return the authenticated user's profile including id and creation date.
    """
    try:
        profile = get_profile(current_user["user_id"])
        return UserOut(**profile)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/me", response_model=UserOut)
async def update_current_user_profile(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the authenticated user's editable profile fields.
    """
    try:
        update_profile(
            current_user["user_id"],
            email=body.email,
            username=body.username,
        )
        profile = get_profile(current_user["user_id"])
        return UserOut(**profile)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_current_user_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Change the authenticated user's password after validating the current one.
    """
    try:
        change_password(
            current_user["user_id"],
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
