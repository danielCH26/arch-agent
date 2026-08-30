"""
LLM Config API — wizard de 3 pasos para configurar el provider + modelo.

Issue: #51 — Wizard obligatorio + filtro de tier MMLU.

Endpoints:
    GET   /api/llm/config              -> LLMConfigOut (api_key nunca se devuelve)
    POST  /api/llm/config              -> save legacy (mantenido por compat)
    POST  /api/llm/config/validate     -> DEPRECATED, retorna 410 Gone

    POST  /api/llm/wizard/step1        -> valida base_url (sin auth)
    POST  /api/llm/wizard/step2        -> valida api_key (auth + conexion)
    POST  /api/llm/wizard/step3        -> guarda config con tier enforcement

El wizard valida incrementalmente y filtra modelos por tier MMLU.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.encryption import decrypt
from app.core.llm_loader import (
    LLMConfigError,
    clear_session_cache,
    load_user_llm_config,
    save_user_llm_config,
    update_user_base_url_only,
    update_user_credentials,
    update_user_model_only,
)
from app.core.model_classifier import classify_model
from app.core.llm_validator import (
    DEFAULT_TIMEOUT,
    LLMValidationError,
    get_available_models,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm-config"])


# --- Pydantic models ---------------------------------------------------------

class LLMConfigOut(BaseModel):
    base_url: Optional[str] = None
    model: Optional[str] = None
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


class WizardStep1Request(BaseModel):
    base_url: str


class WizardStep2Request(BaseModel):
    base_url: str
    api_key: str


class WizardStep3Request(BaseModel):
    base_url: str
    # Opcional: si esta vacio, el endpoint reusa la api_key guardada del usuario
    # (caso de uso "Cambiar modelo" en el wizard, donde el user no re-ingresa key).
    api_key: Optional[str] = None
    model: str
    allow_unknown_model: bool = False


class WizardStepResponse(BaseModel):
    success: bool
    message: str
    # Solo step3 devuelve modelo guardado
    model: Optional[str] = None
    base_url: Optional[str] = None
    has_api_key: Optional[bool] = None


# --- Helpers -----------------------------------------------------------------

def _normalize_base_url(base_url: str) -> str:
    """Quita slash final."""
    return base_url.rstrip("/")


def _validate_url_format(base_url: str) -> None:
    """Validacion client-side del formato. 400 si falla."""
    # Check empty or whitespace-only
    stripped = base_url.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="La URL es obligatoria.")

    # Check protocol
    if not stripped.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="La URL debe comenzar con http:// o https://.",
        )

    # Check host is present using urlparse
    parsed = urlparse(stripped)
    if not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="La URL está incompleta. Ingresá el host, por ejemplo: https://api.openai.com/v1",
        )

    # Additional validation: hostname must have at least one alphanumeric char
    # Use a simple pattern to verify there's a real host (not just scheme://)
    if not re.match(r"^[a-zA-Z0-9]", parsed.hostname):
        raise HTTPException(
            status_code=400,
            detail="La URL está incompleta. Ingresá el host, por ejemplo: https://api.openai.com/v1",
        )


def _ping_models_endpoint(
    base_url: str,
    api_key: Optional[str] = None,
    require_auth: bool = False,
) -> None:
    """
    Hace GET {base_url}/models. Si require_auth=True, agrega Bearer.

    Raises:
        HTTPException con detalle específico (400 para todos los casos).
    """
    url = f"{_normalize_base_url(base_url)}/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=400,
            detail=f"El proveedor no respondió en {DEFAULT_TIMEOUT}s. Verifica tu conexión.",
        )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=400,
            detail="No se pudo conectar al proveedor. Verificá que la URL sea correcta y que el servicio esté activo.",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error de red: {str(e)[:200]}",
        )

    # Validacion de la respuesta
    if response.status_code == 200:
        return  # OK
    if response.status_code == 404:
        raise HTTPException(
            status_code=400,
            detail="La URL no es compatible con OpenAI. Verificá que el endpoint /models exista.",
        )
    if response.status_code == 401:
        if require_auth:
            raise HTTPException(
                status_code=400,
                detail="API Key inválida.",
            )
        # Sin auth, 401 esta OK (significa que el endpoint existe y requiere auth)
        return
    if response.status_code == 403:
        if require_auth:
            raise HTTPException(
                status_code=400,
                detail="Acceso denegado. Verifica tu API key.",
            )
        return
    # Otro status (5xx, etc)
    raise HTTPException(
        status_code=400,
        detail=f"Error del proveedor: {response.status_code} - {response.text[:200]}",
    )


# --- Endpoints existentes (compat) -----------------------------------------

@router.get("/config", response_model=LLMConfigOut)
async def get_config(current_user: dict = Depends(get_current_user)):
    """Get current LLM config (api_key is never returned)."""
    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.id == current_user["user_id"]).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )

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
    """
    Save LLM config (legacy, sin tier enforcement). Mantenido por compat.
    Para tier enforcement usar POST /api/llm/wizard/step3.
    """
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
        logger.exception("Error guardando config LLM (legacy)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post("/config/validate")
async def validate_config_deprecated(body: ValidateRequest):
    """
    DEPRECATED — el wizard lo reemplaza.

    Retorna 410 Gone con un mensaje claro apuntando a los nuevos endpoints.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Este endpoint esta deprecado. "
            "Usa POST /api/llm/wizard/step1 (valida URL) o "
            "POST /api/llm/wizard/step2 (valida key + conexion)."
        ),
    )


# --- Wizard endpoints --------------------------------------------------------

@router.post("/wizard/step1", response_model=WizardStepResponse)
async def wizard_step1(
    body: WizardStep1Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 1: valida la Base URL del provider y la persiste en DB.

    Ping a {base_url}/models con key dummy. Acepta 200/401/403 (endpoint
    existe), rechaza 404 (endpoint no existe), timeout, conn error.

    Si la validacion pasa, persiste SOLO el base_url. La api_key y el
    model no se tocan en este paso — eso lo hacen step2 y step3
    respectivamente. Esto garantiza que el endpoint available-models
    (que lee base_url de DB) vea la URL nueva apenas se valida.
    """
    _validate_url_format(body.base_url)

    # Llama al endpoint sin auth — solo queremos saber si existe
    try:
        _ping_models_endpoint(body.base_url, api_key=None, require_auth=False)
    except LLMValidationError:
        # Wrapper legacy si algo cambia — actualmente _ping_models_endpoint
        # ya levanta HTTPException directo, este except queda como safety net
        raise HTTPException(status_code=400, detail="URL no responde /models")

    # Persistir base_url (atomicamente, sin tocar api_key ni model)
    try:
        update_user_base_url_only(
            current_user["user_id"], _normalize_base_url(body.base_url)
        )
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return WizardStepResponse(
        success=True,
        message="URL válida y guardada. Continúa al paso 2.",
        base_url=body.base_url,
    )


@router.post("/wizard/step2", response_model=WizardStepResponse)
async def wizard_step2(
    body: WizardStep2Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 2: valida la API Key contra el endpoint autenticado y la persiste.

    Pega a {base_url}/models con Bearer. 200 = conexion OK. 401 = key inválida.

    Si la validacion pasa, persiste base_url + api_key (encriptada) en una
    sola transaccion, SIN tocar llm_model para no borrar el modelo que el
    usuario ya tenia configurado. Asi, cuando el frontend llame a
    available-models desde step3, ya tendra las credenciales correctas.
    """
    _validate_url_format(body.base_url)

    if not body.api_key or not body.api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="La API key es obligatoria",
        )

    # _ping_models_endpoint con api_key y require_auth=True
    _ping_models_endpoint(body.base_url, api_key=body.api_key, require_auth=True)

    # Persistir base_url + api_key encriptada (NO toca model)
    try:
        update_user_credentials(
            current_user["user_id"],
            _normalize_base_url(body.base_url),
            body.api_key.strip(),
        )
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return WizardStepResponse(
        success=True,
        message="Conexión exitosa y credenciales guardadas. Continúa al paso 3.",
        base_url=body.base_url,
        has_api_key=True,
    )


@router.post("/wizard/step3", response_model=WizardStepResponse)
async def wizard_step3(
    body: WizardStep3Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Step 3: selecciona el modelo y lo persiste. Tier enforcement.

    Asume que base_url y api_key ya estan persistidos en DB (por step1 y
    step2, o por una configuracion anterior valida). Lee la config actual
    para validar que existe; si no hay config previa -> 404 con mensaje
    claro apuntando a los pasos 1 y 2.

    Si el body trae base_url/api_key del state del frontend, se ignoran:
    la fuente de verdad es la DB (mantiene consistencia si hay varias
    pestanas abiertas, etc.).

    Reglas:
      - Si no hay config previa (base_url o api_key faltantes) -> 404
      - Si el modelo NO esta en el YAML (unknown) y allow_unknown_model=False -> 400
      - Si el modelo es tier2 (MMLU 60-85) y allow_unknown_model=False -> 400
      - Si el modelo es blocked (MMLU < 60) -> 400 SIEMPRE (no override)
      - Si el modelo es tier1 -> OK siempre
      - Si el modelo es unknown/tier2 y allow_unknown_model=True -> OK (warning)
    """
    if not body.model or not body.model.strip():
        raise HTTPException(status_code=400, detail="El modelo es obligatorio")

    # Cargar config actual de DB. step1 y step2 ya debieron persistir
    # base_url + api_key; si no estan, devolvemos 404 claro.
    try:
        existing = load_user_llm_config(current_user["user_id"])
    except LLMConfigError as e:
        if e.reason == "decryption_failed":
            logger.warning(
                "user_id=%s tiene config con API key que no se puede desencriptar",
                current_user["user_id"],
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "La API key guardada no se puede desencriptar. "
                    "Probablemente cambio ENCRYPTION_KEY del backend. "
                    "Reconfigura tu LLM con el paso 1."
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=(
                "No hay config LLM persistida. Completá los pasos 1 y 2 primero."
            ),
        )

    classification = classify_model(body.model)

    if classification.tier == "blocked":
        raise HTTPException(
            status_code=400,
            detail=(
                f"El modelo '{body.model}' (MMLU {classification.mmlu_score}) "
                "esta bloqueado. No se puede usar."
            ),
        )

    if classification.tier in ("tier2", "unknown") and not body.allow_unknown_model:
        score_str = (
            f"{classification.mmlu_score}"
            if classification.mmlu_score is not None
            else "desconocido"
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"El modelo '{body.model}' (MMLU {score_str}) no esta en tier 1. "
                "Para forzar, envia allow_unknown_model=true."
            ),
        )

    if classification.tier in ("tier2", "unknown") and body.allow_unknown_model:
        logger.warning(
            "wizard_step3: user_id=%s guarda modelo NO tier1: %s (tier=%s, mmlu=%s)",
            current_user["user_id"],
            body.model,
            classification.tier,
            classification.mmlu_score,
        )

    # Persistir SOLO el modelo. base_url y api_key ya estan en DB.
    try:
        update_user_model_only(current_user["user_id"], body.model.strip())
    except LLMConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return WizardStepResponse(
        success=True,
        message="Configuración guardada correctamente",
        model=body.model,
        base_url=existing.base_url,
        has_api_key=True,
    )


class AvailableModelsResponse(BaseModel):
    models: list[str]
    base_url: str
    cached: bool = False


@router.get("/wizard/available-models", response_model=AvailableModelsResponse)
async def wizard_available_models(
    current_user: dict = Depends(get_current_user),
):
    """
    Lista los modelos disponibles del provider guardado del usuario.

    Desencripta la API key guardada en DB y consulta {base_url}/models.
    La api_key NUNCA se devuelve al frontend (se usa solo server-side).

    Pensado para que el paso 3 del wizard muestre la lista actual del provider
    sin pedirle al usuario que re-ingrese la key.
    """
    try:
        config = load_user_llm_config(current_user["user_id"])
    except LLMConfigError as e:
        if e.reason == "decryption_failed":
            # La config existe en DB pero la API key esta corrupta
            # (probablemente cambio ENCRYPTION_KEY del backend).
            # Distinto de "no config" -> el cliente necesita saber que
            # tiene que reconfigurar.
            logger.warning(
                "user_id=%s tiene config con API key que no se puede desencriptar",
                current_user["user_id"],
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "La API key guardada no se puede desencriptar. "
                    "Probablemente cambio ENCRYPTION_KEY del backend. "
                    "Reconfigura tu LLM con el paso 1."
                ),
            )
        # "missing" u otro motivo: no hay config utilizable.
        raise HTTPException(
            status_code=404,
            detail="No hay config LLM guardada. Completá los pasos 1 y 2 primero.",
        )

    if config is None or not config.base_url or not config.api_key:
        raise HTTPException(
            status_code=404,
            detail="No hay config LLM guardada. Completá los pasos 1 y 2 primero.",
        )

    # get_available_models acepta api_key encriptada O en plano.
    # Le pasamos la desencriptada porque decrypt() requiere ENCRYPTION_KEY
    # y queremos que este endpoint funcione solo si el backend tiene la key.
    api_key_plain = config.api_key

    try:
        models = get_available_models(
            base_url=config.base_url,
            api_key=api_key_plain,
            user_id=current_user["user_id"],
            force_refresh=False,  # usa cache 24h si existe
        )
    except LLMValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo listar modelos: {e}",
        )
    except Exception as e:
        logger.exception("Error listando modelos del provider")
        raise HTTPException(status_code=500, detail=str(e))

    return AvailableModelsResponse(
        models=models,
        base_url=config.base_url,
        cached=True,
    )