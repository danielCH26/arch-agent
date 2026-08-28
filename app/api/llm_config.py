import httpx

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.encryption import decrypt
from app.core.llm_loader import load_user_llm_config, save_user_llm_config, clear_session_cache, LLMConfigError
from app.core.llm_validator import validate_llm_config, LLMValidationError

router = APIRouter(prefix="/api/llm", tags=["llm-config"])


# --- Pydantic models ----------------------------------------------------------

class LLMConfigOut(BaseModel):
    base_url: str | None
    model: str | None
    has_api_key: bool


class LLMConfigSave(BaseModel):
    base_url: str
    model: str
    api_key: str


class ValidateRequest(BaseModel):
    base_url: str
    api_key: str
    model: str


class ValidateResponse(BaseModel):
    valid: bool
    message: str


# --- Routes ------------------------------------------------------------------

@router.get("/config", response_model=LLMConfigOut)
async def get_config(current_user: dict = Depends(get_current_user)):
    """Get current LLM config (api_key is never returned)."""
    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.id == current_user["user_id"]).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

        return LLMConfigOut(
            base_url=user.llm_base_url,
            model=user.llm_model,
            has_api_key=bool(user.encrypted_api_key),
        )
    finally:
        db.close()


@router.post("/config", response_model=dict)
async def save_config(
    body: LLMConfigSave,
    current_user: dict = Depends(get_current_user),
):
    """Save LLM config (base_url, model, api_key). API key is encrypted before storage."""
    try:
        save_user_llm_config(
            user_id=current_user["user_id"],
            base_url=body.base_url,
            model=body.model,
            api_key=body.api_key,
        )
        return {"message": "Configuración guardada correctamente"}
    except LLMConfigError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/config/validate", response_model=ValidateResponse)
async def validate_config(
    body: ValidateRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Validate LLM config by making a test call to the provider's /models endpoint.
    Does NOT save anything.
    """
    try:
        validate_llm_config(body.base_url, body.api_key)
        return ValidateResponse(valid=True, message="Configuración válida")
    except LLMValidationError as e:
        return ValidateResponse(
            valid=False,
            message=f"Configuración inválida: {e}",
        )
    except Exception as e:
        return ValidateResponse(valid=False, message=f"Error inesperado: {str(e)[:200]}")
