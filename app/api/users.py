from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.api.dependencies import get_current_user
from app.auth.profile import get_profile, update_profile
from app.auth.validators import ValidationError

router = APIRouter(prefix="/api/users", tags=["users"])


# --- Request/Response models -------------------------------------------------


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: Optional[str] = None


class UserProfileUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None


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


@router.put("/me", response_model=UserOut)
async def update_current_user_profile(
    updates: UserProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    """
    Update the authenticated user's profile.
    Only provided fields (non-None) will be updated.
    """
    # If both fields are None, return current profile
    if updates.username is None and updates.email is None:
        try:
            profile = get_profile(current_user["user_id"])
            return UserOut(**profile)
        except ValidationError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    try:
        profile = update_profile(
            user_id=current_user["user_id"],
            username=updates.username,
            email=updates.email,
        )
        # Include id and created_at from get_profile
        full_profile = get_profile(current_user["user_id"])
        return UserOut(**full_profile)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
