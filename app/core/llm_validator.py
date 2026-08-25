"""
Validación de configuración LLM y listado de modelos disponibles.

Issue: #7 - HU12 Configuración de LLM
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional

from app.core.encryption import decrypt


# Timeout configurable
DEFAULT_TIMEOUT = 10.0  # segundos

# Cache TTL
CACHE_TTL_HOURS = 24


class LLMValidationError(Exception):
    """Error específico de validación LLM."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _normalize_base_url(base_url: str) -> str:
    """Quita slash final del base_url si existe."""
    return base_url.rstrip("/")


def validate_llm_config(base_url: str, api_key: str) -> bool:
    """
    Valida que la configuración LLM sea correcta haciendo GET {base_url}/models.

    Args:
        base_url: URL base del proveedor (ej: https://api.openai.com/v1)
        api_key: API key del proveedor

    Returns:
        True si la configuración es válida

    Raises:
        LLMValidationError: si falla la validación (con mensaje específico)
    """
    if not base_url or not api_key:
        raise LLMValidationError("base_url y api_key son obligatorios")

    url = f"{_normalize_base_url(base_url)}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = httpx.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            raise LLMValidationError(
                "API Key inválida.", status_code=401
            )
        elif response.status_code == 404:
            raise LLMValidationError(
                "La URL no existe o no es un endpoint /models válido.",
                status_code=404,
            )
        else:
            raise LLMValidationError(
                f"Error del proveedor: {response.status_code} - {response.text[:200]}",
                status_code=response.status_code,
            )

    except httpx.TimeoutException:
        raise LLMValidationError(
            f"El proveedor no respondió en {DEFAULT_TIMEOUT}s. Verifica tu conexión."
        )
    except httpx.ConnectError as e:
        raise LLMValidationError(
            f"No se pudo conectar al proveedor: {str(e)[:200]}"
        )
    except httpx.RequestError as e:
        raise LLMValidationError(
            f"Error de red: {str(e)[:200]}"
        )


def get_available_models(
    base_url: str,
    api_key: str,
    user_id: int,
    engram_client=None,
    force_refresh: bool = False,
) -> list[str]:
    """
    Lista los modelos disponibles del proveedor, con cache en Engram.

    Args:
        base_url: URL base del proveedor
        api_key: API key (puede estar encriptada o en plano)
        user_id: ID del usuario (para cache key)
        engram_client: cliente Engram (opcional, para tests)
        force_refresh: si True, ignora cache y consulta la API

    Returns:
        Lista de IDs de modelos disponibles

    Raises:
        LLMValidationError: si falla la consulta
    """
    cache_key = f"models_cache:user_{user_id}"

    # 1. Intentar usar cache (si no es force_refresh)
    if not force_refresh and engram_client is not None:
        cached = _get_cached_models(engram_client, cache_key)
        if cached:
            return cached

    # 2. Consultar API
    url = f"{_normalize_base_url(base_url)}/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = httpx.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        models = [m["id"] for m in data.get("data", [])]

        # 3. Guardar en cache
        if engram_client is not None and models:
            _save_cache(engram_client, cache_key, models)

        return models

    except httpx.TimeoutException:
        raise LLMValidationError(
            f"Timeout al listar modelos ({DEFAULT_TIMEOUT}s)"
        )
    except httpx.HTTPStatusError as e:
        raise LLMValidationError(
            f"Error del proveedor: {e.response.status_code}",
            status_code=e.response.status_code,
        )
    except Exception as e:
        raise LLMValidationError(f"Error al listar modelos: {str(e)[:200]}")


def _get_cached_models(engram_client, cache_key: str) -> Optional[list[str]]:
    """
    Recupera modelos del cache si está vigente.

    Returns:
        Lista de modelos si cache válido, None si no hay o expiró.
    """
    try:
        # Búsqueda simple en Engram (búsqueda por topic_key)
        results = engram_client.search(query=cache_key, limit=1)
        if not results:
            return None

        for result in results:
            observation_id = result.get("id")
            if not observation_id:
                continue
            observation = engram_client.get_observation(id=observation_id)
            fetched_at_str = observation.get("fetched_at")
            models = observation.get("models")

            if not fetched_at_str or not models:
                continue

            fetched_at = datetime.fromisoformat(fetched_at_str)
            if datetime.now() - fetched_at < timedelta(hours=CACHE_TTL_HOURS):
                return models

        return None
    except Exception:
        return None  # Cache miss silencioso


def _save_cache(engram_client, cache_key: str, models: list[str]) -> None:
    """Guarda modelos en Engram con timestamp."""
    try:
        engram_client.save(
            topic_key=cache_key,
            content={
                "models": models,
                "fetched_at": datetime.now().isoformat(),
            },
            title=f"Models cache for {cache_key}",
            type="cache",
        )
    except Exception:
        pass  # Cache best-effort


def invalidate_cache(engram_client, user_id: int) -> None:
    """Invalida el cache de modelos de un usuario."""
    cache_key = f"models_cache:user_{user_id}"
    try:
        engram_client.delete(topic_key=cache_key)
    except Exception:
        pass  # Best-effort
