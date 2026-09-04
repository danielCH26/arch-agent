"""
Carga de configuración LLM del usuario y construcción del modelo LangChain.

Issue: #7 - HU12 Configuración de LLM
"""

import os
from dataclasses import dataclass
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.database import SessionLocal
from app.models.user import User
from app.core.encryption import decrypt, EncryptionError


class LLMConfigError(Exception):
    """El usuario no tiene configuración LLM válida."""

    def __init__(self, message: str, reason: str = "missing"):
        super().__init__(message)
        # Sub-tipo del error. Call sites pueden inspeccionarlo para
        # distinguir entre "no config" y otros modos de falla.
        # Valores esperados: "missing", "decryption_failed", "user_not_found".
        self.reason = reason


@dataclass
class UserLLMConfig:
    """Configuración LLM de un usuario, ya desencriptada."""
    user_id: int
    base_url: str
    model: str
    api_key: str  # desencriptada


# Cache en memoria por sesión (se invalida al cerrar chat)
_session_cache: dict[int, tuple[UserLLMConfig, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutos


def load_user_llm_config(user_id: int) -> UserLLMConfig:
    """
    Carga la configuración LLM del usuario desde la DB.

    Args:
        user_id: ID del usuario

    Returns:
        UserLLMConfig con la API key ya desencriptada y el model (puede
        ser vacio si el user no completo todavia el step3 del wizard).

    Raises:
        LLMConfigError: si el usuario no tiene config o está corrupta

    Nota historica: antes esta funcion requeria que `llm_model` estuviera
    seteado, pero eso rompe el flujo del wizard: despues de step2 el
    user tiene base_url + api_key guardadas pero todavia no eligio
    modelo, asi que available-models (que se llama justo despues de
    step2) falla con 404. Por eso ahora solo exigimos base_url +
    api_key. La validacion de model vacio se hace mas adelante (en
    build_langchain_model, que es donde realmente importa).
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise LLMConfigError(f"Usuario {user_id} no encontrado")

        if not user.llm_base_url:
            raise LLMConfigError(
                f"Usuario {user_id} no tiene URL base configurada. "
                "Completa el paso 1 del wizard primero."
            )

        if not user.encrypted_api_key:
            raise LLMConfigError(
                f"Usuario {user_id} no tiene API key configurada. "
                "Completa el paso 2 del wizard primero."
            )

        # Desencriptar API key
        try:
            api_key = decrypt(user.encrypted_api_key)
        except EncryptionError as e:
            raise LLMConfigError(
                f"No se pudo desencriptar la API key: {e}",
                reason="decryption_failed",
            )

        return UserLLMConfig(
            user_id=user_id,
            base_url=user.llm_base_url,
            model=user.llm_model,
            api_key=api_key,
        )
    finally:
        db.close()


def build_langchain_model(
    user_id: int,
    force_reload: bool = False,
) -> BaseChatModel:
    """
    Construye el modelo LangChain para el usuario.

    Usa cache en memoria (5 min TTL) para evitar recargar la config en cada
    llamada al agente.

    Args:
        user_id: ID del usuario
        force_reload: si True, ignora cache

    Returns:
        Instancia de ChatModel lista para usar

    Raises:
        LLMConfigError: si no se puede construir el modelo
    """
    import time

    # 1. Verificar cache
    if not force_reload and user_id in _session_cache:
        cached_config, expires_at = _session_cache[user_id]
        if time.time() < expires_at:
            return _init_model(cached_config)

    # 2. Cargar config fresca desde DB
    config = load_user_llm_config(user_id)

    # 3. Cachear
    _session_cache[user_id] = (config, time.time() + _CACHE_TTL_SECONDS)

    # 4. Construir modelo
    return _init_model(config)


def _init_model(config: UserLLMConfig) -> BaseChatModel:
    """Inicializa el modelo LangChain con la config del usuario."""
    try:
        model = init_chat_model(
            model=config.model,
            model_provider="openai",  # Cualquier API OpenAI-compatible
            base_url=config.base_url,
            api_key=config.api_key,
        )
        return model
    except Exception as e:
        raise LLMConfigError(
            f"No se pudo inicializar el modelo {config.model}: {e}"
        )


def clear_session_cache(user_id: Optional[int] = None) -> None:
    """
    Limpia el cache de modelos. Si user_id es None, limpia todo.

    Útil cuando:
    - El usuario cambia su config LLM
    - La sesión del chat termina
    """
    if user_id is None:
        _session_cache.clear()
    elif user_id in _session_cache:
        del _session_cache[user_id]


def save_user_llm_config(
    user_id: int,
    base_url: str,
    model: str,
    api_key: str,
) -> None:
    """
    Guarda (o actualiza) la configuración LLM completa del usuario.

    Encripta la API key antes de guardar. Usado por el endpoint legacy
    POST /api/llm/config. Para los steps del wizard, usar los helpers
    granulares (update_user_base_url_only, update_user_credentials,
    update_user_model_only) que preservan el resto de la config.

    Args:
        user_id: ID del usuario
        base_url: URL base del proveedor
        model: nombre del modelo
        api_key: API key en texto plano (se encripta antes de guardar)
    """
    from app.core.encryption import encrypt

    encrypted_key = encrypt(api_key)

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise LLMConfigError(f"Usuario {user_id} no encontrado")

        user.llm_base_url = base_url
        user.llm_model = model
        user.encrypted_api_key = encrypted_key
        db.commit()
    finally:
        db.close()
        # Invalidar cache
        clear_session_cache(user_id)


def update_user_base_url_only(user_id: int, base_url: str) -> None:
    """
    Actualiza solo el base_url del usuario, sin tocar api_key ni model.

    Usado por wizard step1 para persistir la URL apenas se valida, de modo
    que el siguiente llamado a /api/llm/wizard/available-models (que lee de
    DB) vea la URL nueva y devuelva modelos del provider correcto.
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise LLMConfigError(f"Usuario {user_id} no encontrado")
        user.llm_base_url = base_url
        db.commit()
    finally:
        db.close()
        clear_session_cache(user_id)


def update_user_credentials(user_id: int, base_url: str, api_key: str) -> None:
    """
    Actualiza base_url + api_key (encriptada) en una sola transaccion.

    Usado por wizard step2. NO toca llm_model para no borrar el modelo
    que el usuario ya tenia configurado.
    """
    from app.core.encryption import encrypt

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise LLMConfigError(f"Usuario {user_id} no encontrado")
        user.llm_base_url = base_url
        user.encrypted_api_key = encrypt(api_key)
        db.commit()
    finally:
        db.close()
        clear_session_cache(user_id)


def update_user_model_only(user_id: int, model: str) -> None:
    """
    Actualiza solo el model del usuario, sin tocar base_url ni api_key.

    Usado por wizard step3. Asume que base_url y api_key ya estan en DB
    (persistidos por step1/step2 o por un save anterior).
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            raise LLMConfigError(f"Usuario {user_id} no encontrado")
        user.llm_model = model
        db.commit()
    finally:
        db.close()
        clear_session_cache(user_id)
