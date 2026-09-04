from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.api.dependencies import get_current_user
from app.auth.profile import get_profile
from app.auth.validators import ValidationError

router = APIRouter(prefix="/api/users", tags=["users"])


# --- Request/Response models -------------------------------------------------


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: Optional[str] = None


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
