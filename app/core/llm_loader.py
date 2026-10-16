"""
Carga de configuración LLM del usuario y construcción del modelo LangChain.

Issue: #7 - HU12 Configuración de LLM
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.database import SessionLocal
from app.models.user import User
from app.core.encryption import decrypt, EncryptionError


# Temperatura de muestreo para TODO modelo que construye la app.
#
# Groq y OpenAI usan 1.0 por defecto, que es el maximo de aleatoriedad: dos
# turnos identicos con el mismo prompt devuelven respuestas distintas. Nadie lo
# eligio -- simplemente nadie lo escribio, asi que produccion venia muestreando
# al maximo. El cliente necesita salida estable: la misma proposal tiene que ser
# comparable entre iteraciones y entre ejecuciones del golden set, y una
# temperatura alta convierte cada regeneracion en un producto distinto. Se fija
# 0.0 de forma explicita en vez de heredar el default del proveedor.
#
# No todos los modelos aceptan el parametro. La serie de razonamiento `o*` y la
# serie `gpt-5*` (salvo `gpt-5-chat*`) de OpenAI solo admiten temperature=1 y
# responden 400 ante cualquier otro valor, asi que a esos NO se les manda: se
# omite el kwarg y el request sale sin `temperature`, con lo que aplica el
# default de la API (1). Ver `_acepta_temperature`.
DEFAULT_LLM_TEMPERATURE: float = 0.0


# Series de modelos que rechazan `temperature` distinto de 1 (400 de OpenAI).
#
# El criterio es la convencion de nomenclatura, NO una lista de nombres:
#
# - ``o`` + digito: toda la familia de razonamiento (o1, o1-mini, o1-pro,
#   o1-2024-12-17, o3, o3-mini, o3-pro, o4-mini, ...). Una generacion futura
#   (o2, o5) queda cubierta sin tocar el codigo. `gpt-4o`, `gpt-4o-mini` y
#   `llama-3.3-70b` no arrancan con `o` + digito, asi que no entran.
# - ``gpt-5`` sin ``chat`` en el nombre: gpt-5, gpt-5-mini, gpt-5-nano,
#   gpt-5.1, ... `gpt-5-chat-latest` si acepta temperatura y queda afuera.
#
# Asimetria de errores: un falso positivo solo omite la temperatura (el modelo
# muestrea con el default del provider, inocuo); un falso negativo rompe el
# request con 400. Por eso la regex prefiere matchear de mas.
#
# Sobre langchain (verificado con langchain-openai 1.6.2,
# ``ChatOpenAI.validate_temperature``):
# - Para `o1*` fuerza temperature=1 SOLO si el caller no paso el kwarg. Para
#   `o3*`/`o4*` no hace nada: si se omite, el valor queda en None, no viaja en
#   el request y la API aplica su propio default.
# - Para `gpt-5*` no-chat descarta el valor en silencio, pero decide con
#   ``model.lower().startswith("gpt-5")``: un nombre con prefijo de provider
#   (``openai/gpt-5``) no matchea y el 0.0 llegaria al request. Por eso
#   `gpt-5` se resuelve aca y no se delega a la libreria.
#
# Formato de los nombres: los gateways OpenAI-compatibles como OpenRouter
# exponen los modelos como ``provider/modelo`` (``openai/o1-mini``,
# ``openai/gpt-5-mini``). El ancla ``(?:^|/)`` matchea tanto el nombre pelado
# como el prefijado. Esto tambien aplica a cualquier provider: un segmento
# ``/o\d`` (``anthropic/o3``) omite la temperatura, decision deliberada por la
# asimetria de errores de arriba.
#
# Punto de extension: si manana otra familia tiene la misma restriccion, su
# patron se agrega ACA. Para nombres arbitrarios que ninguna regex puede
# adivinar (deployments de Azure tipo ``my-o1-deployment``) esta
# ``LLM_MODELS_WITHOUT_TEMPERATURE``, ver `_modelos_sin_temperature_env`.
_RECHAZA_TEMPERATURE_RE = re.compile(r"(?:^|/)(?:o\d|gpt-5(?![^/]*chat))")

# Variable de entorno con nombres de modelo (separados por coma, sin distinguir
# mayusculas) a los que nunca se les manda `temperature`, ademas de los que
# detecta `_RECHAZA_TEMPERATURE_RE`.
LLM_MODELS_WITHOUT_TEMPERATURE_ENV = "LLM_MODELS_WITHOUT_TEMPERATURE"


def _modelos_sin_temperature_env() -> frozenset[str]:
    """Nombres listados en ``LLM_MODELS_WITHOUT_TEMPERATURE``, normalizados."""
    raw = os.getenv(LLM_MODELS_WITHOUT_TEMPERATURE_ENV, "")
    return frozenset(m.strip().lower() for m in raw.split(",") if m.strip())


def _acepta_temperature(model: str) -> bool:
    """¿Este modelo acepta un valor de `temperature` distinto de 1?

    Args:
        model: nombre del modelo tal como lo eligio el usuario en el wizard,
            con o sin prefijo de provider (``openai/``, ``groq/``, ``azure/``).

    Returns:
        True si se le puede pasar `temperature` (ej. `gpt-4o-mini`,
        `llama-3.3-70b`, `openai/gpt-4o-mini`, `gpt-5-chat-latest`). False si
        hay que omitir el kwarg (ej. `o1`, `o3-mini`, `openai/o1-mini`,
        `gpt-5`, `openai/gpt-5-mini`, o un nombre listado en
        ``LLM_MODELS_WITHOUT_TEMPERATURE``).
    """
    normalizado = (model or "").strip().lower()
    if normalizado in _modelos_sin_temperature_env():
        return False
    return not _RECHAZA_TEMPERATURE_RE.search(normalizado)


def explain_llm_error(exc: BaseException) -> str:
    """Mensaje para el usuario ante un error del provider en request time.

    Si el provider rechazo el parametro `temperature` (400), el texto crudo no
    dice que hacer; se reemplaza por uno que nombra la causa y la salida
    (``LLM_MODELS_WITHOUT_TEMPERATURE``). Cualquier otro error pasa tal cual.
    """
    texto = str(exc)
    if "temperature" in texto.lower():
        return (
            "El modelo configurado rechazo el parametro 'temperature'. "
            "Si es un modelo de razonamiento con un nombre no estandar (por "
            "ejemplo un deployment de Azure), agregalo a la variable de entorno "
            f"{LLM_MODELS_WITHOUT_TEMPERATURE_ENV}. Detalle del provider: {texto}"
        )
    return texto


class LLMConfigError(Exception):
    """El usuario no tiene configuración LLM válida."""

    def __init__(self, message: str, reason: str = "missing"):
        super().__init__(message)
        # Sub-tipo del error. Call sites pueden inspeccionarlo para
        # distinguir entre "no config" y otros modos de falla.
        # Valores esperados: "missing", "decryption_failed", "user_not_found",
        # "initialization_failed".
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
            model=user.llm_model or "",
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
    if not config.model:
        raise LLMConfigError(
            f"Usuario {config.user_id} no tiene modelo configurado. "
            "Completa el paso 3 del wizard primero.",
            reason="missing",
        )

    kwargs: dict = {
        "model": config.model,
        "model_provider": "openai",  # Cualquier API OpenAI-compatible
        "base_url": config.base_url,
        "api_key": config.api_key,
    }
    # Solo se manda `temperature` si el modelo lo admite. Omitirlo no es un
    # descuido: es lo unico que hace que la serie `o*` funcione, porque su unico
    # valor valido es 1 y mandarle 0.0 produce un 400 en request time (que
    # aflora como SSE `event: error` sin explicar la causa).
    if _acepta_temperature(config.model):
        kwargs["temperature"] = DEFAULT_LLM_TEMPERATURE

    try:
        model = init_chat_model(**kwargs)
        return model
    except Exception as e:
        raise LLMConfigError(
            f"No se pudo inicializar el modelo {config.model}: {e}",
            reason="initialization_failed",
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
