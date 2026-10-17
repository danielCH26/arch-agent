"""
Carga de configuración LLM del usuario y construcción del modelo LangChain.

Issue: #7 - HU12 Configuración de LLM
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.database import SessionLocal
from app.models.user import User
from app.core.encryption import decrypt, EncryptionError

_LOGGER = logging.getLogger(__name__)


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
# No todos los modelos aceptan el parametro. La serie de razonamiento `o*` de
# OpenAI solo admite temperature=1 y responde 400 ante cualquier otro valor, asi
# que aca NO se manda: se omite el kwarg y langchain aplica su default de 1, que
# es el unico valor esos modelos soportan. Ver `_acepta_temperature`.
DEFAULT_LLM_TEMPERATURE: float = 0.0


# LLM por defecto del backend, para usuarios que no configuraron uno propio.
#
# Antes, un usuario sin configuracion recibia 409 "LLM not configured" en
# cualquier consulta: la app no era usable sin pasar por el wizard de HU12.
# Con esto, el default es el ultimo recurso, no el primero: si el usuario
# configuro su LLM, el suyo gana siempre.
#
# `DEFAULT_LLM_BASE_URL` es constante y no variable de entorno a proposito. Si
# fuera configurable, cualquiera que pueda tocar el entorno lo apuntaria a otro
# endpoint y el "default del sistema" dejaria de ser un default. La unica parte
# que viene del entorno es la credencial (`GROQ_API_KEY`), que es un secreto del
# operador y por definicion no puede estar hardcodeada.
#
# Modelo: `openai/gpt-oss-120b`. Se evaluo `qwen/qwen3.8-27b` y se descarto --
# es Preview, Groq advierte que "should not be used in production environments as
# they may be discontinued at short notice", cuesta $4.00/1M de output contra
# $0.60 de este, y no tiene baseline medido. Este si: ver el corpus de `evals/`.
DEFAULT_LLM_BASE_URL: str = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL: str = "openai/gpt-oss-120b"


# Series de modelos que rechazan `temperature` distinto de 1 (400 de OpenAI).
#
# El criterio es el prefijo ``o`` seguido de un digito, NO una lista de nombres.
# Es la convencion de nomenclatura de toda la familia de razonamiento de OpenAI
# (letra + generacion): o1, o1-mini, o1-pro, o1-2024-12-17, o3, o3-mini, o3-pro,
# o4-mini, ... asi una generacion futura (o2, o5) queda cubierta sin tocar el
# codigo. Ningun modelo ajeno a esa familia entra por accidente: `gpt-4o`,
# `gpt-4o-mini` y `llama-3.3-70b` no arrancan con `o` + digito.
#
# Sobre langchain: `langchain_openai.chat_models.base.ChatOpenAI` tiene su propia
# guarda (base.py ~1118) que fuerza temperature=1 para `o1*`, pero SOLO cuando el
# parametro NO viene en `values` -- y la app lo manda explicito, con lo cual la
# guarda nunca dispara y el 0.0 viaja al request. Para `gpt-5*` no-chat langchain
# hace `values.pop("temperature")` y descarta el valor en silencio, asi que ese
# caso lo cubre la libreria y no se replica acá. Ademas la guarda de langchain
# solo llega a `o1`: no cubre `o3*` ni `o4*`, que fallan igual.
#
# Punto de extension: si manana otro proveedor -- u otra familia de OpenAI --
# tiene la misma restriccion, su patron se agrega ACa. Este es el unico lugar
# que decide si se manda la temperatura.
#
# Formato de los nombres: los providers OpenAI-style suelen prefijar con
# ``provider/`` (Groq devuelve ``openai/o1-mini`` en ``/v1/models``). La forma
# ``(?:^|/)o\d`` matchea tanto ``o1-mini`` como ``openai/o1-mini``.
_RECHAZA_TEMPERATURE_RE = re.compile(r"(?:^|/)o\d")


def _acepta_temperature(model: str) -> bool:
    """¿Este modelo acepta un valor de `temperature` distinto de 1?

    Funcion pura, sin dependencias: facil de testear y de extender.

    Args:
        model: nombre del modelo tal como lo eligio el usuario en el wizard,
            con o sin prefijo de provider (``openai/``, ``groq/``, ``azure/``).

    Returns:
        True si se le puede pasar `temperature` (ej. `gpt-4o-mini`,
        `llama-3.3-70b`, `openai/gpt-4o-mini`). False si hay que omitir el kwarg
        para que la libreria aplique su default (ej. `o1`, `o1-mini`, `o3-mini`,
        `o4-mini`, `openai/o1-mini`).
    """
    return not _RECHAZA_TEMPERATURE_RE.search((model or "").strip().lower())


class LLMConfigError(Exception):
    """El usuario no tiene configuración LLM válida.

    ``reason`` distingue el modo de falla:
      - ``"not_configured"``: el usuario no tiene base_url + api_key y no hay
        LLM por defecto (o el caller no lo permite).
      - ``"missing"``: tiene base_url + api_key pero no eligió modelo (paso 3
        del wizard).
      - ``"decryption_failed"``: la API key guardada no se puede desencriptar.
      - ``"user_not_found"``: el ``user_id`` no existe.
      - ``"initialization_failed"``: langchain no pudo construir el modelo.

    El mensaje (``str(exc)``) es para logs y para el wizard. A un usuario final
    se le muestra ``user_facing_message(exc)``, que no expone detalles del
    backend (por ejemplo, el nombre de la variable ``GROQ_API_KEY``).
    """

    def __init__(self, message: str, reason: str = "missing"):
        super().__init__(message)
        self.reason = reason


_USER_FACING_MESSAGES = {
    "missing": (
        "Te falta elegir el modelo: completa el paso 3 de la configuración del "
        "LLM para seguir usando tu propia API key."
    ),
    "not_configured": (
        "No hay un modelo de lenguaje configurado. Configura tu proveedor en la "
        "sección de configuración del LLM."
    ),
    "decryption_failed": (
        "No se pudo leer la API key guardada. Vuelve a ingresarla en la "
        "configuración del LLM."
    ),
    "initialization_failed": (
        "No se pudo iniciar el modelo configurado. Revisa el modelo elegido en "
        "la configuración del LLM."
    ),
    "user_not_found": "Usuario no encontrado.",
}


def user_facing_message(exc: "LLMConfigError") -> str:
    """Mensaje para el usuario final según ``exc.reason``.

    Lo usan chat, elicitación y propuestas. En particular, quien completó los
    pasos 1 y 2 del wizard pero no el 3 (``reason="missing"``) recibe un
    mensaje que le dice que le falta elegir el modelo, en vez del genérico.
    """
    return _USER_FACING_MESSAGES.get(exc.reason, _USER_FACING_MESSAGES["not_configured"])


@dataclass
class UserLLMConfig:
    """Configuración LLM de un usuario, ya desencriptada."""

    user_id: int
    base_url: str
    model: str
    api_key: str  # desencriptada
    # De donde salio la config: "user" si el usuario configuro la suya,
    # "system_default" si vino del backend (#98).
    #
    # Sin esto no se puede auditar cuanto trafico consume la key del sistema,
    # que es la unica forma de atribuir gasto cuando la facturacion es una sola.
    source: str = "user"


def _load_system_default(user_id: int) -> Optional[UserLLMConfig]:
    """Construye la config del LLM por defecto, o None si no hay credencial.

    Se resuelve POR FUERA de la cache de sesion a proposito. El caller
    (`build_langchain_model`) tiene la orden explicita de NO escribir configs
    con ``source == "system_default"`` a `_session_cache`: si el default
    entrara al cache por `user_id`, un usuario que lo recibiera y despues
    completara el wizard seguiria viendo el default hasta que expiraran los
    300s de TTL: configuraria su modelo y no veria ningun cambio. Resolverlo
    siempre fresco cuesta una llamada a la DB solo en el camino no-configurado,
    que es el raro.

    Returns:
        UserLLMConfig con el default, o None si `GROQ_API_KEY` no esta definida
        o esta vacia. None no es un error todavia: el caller decide.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    return UserLLMConfig(
        user_id=user_id,
        base_url=DEFAULT_LLM_BASE_URL,
        model=DEFAULT_LLM_MODEL,
        api_key=api_key,
        source="system_default",
    )


# Cache en memoria por sesión (se invalida al cerrar chat)
_session_cache: dict[int, tuple[UserLLMConfig, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutos


def load_user_llm_config(user_id: int, allow_default: bool = True) -> UserLLMConfig:
    """
    Carga la configuración LLM del usuario desde la DB.

    Orden de resolución:
      1. Si el usuario tiene base_url + api_key, se usa SU config (la propia
         siempre gana). Si además le falta el modelo:
           - con ``allow_default=True`` (chat, elicitación, propuestas) se
             lanza ``reason="missing"``: no se completa con el modelo del
             default, porque mezclar su endpoint con un modelo de Groq da un
             400 en el primer request;
           - con ``allow_default=False`` (wizard: step3 y available-models) se
             devuelve con ``model=""``, porque esos endpoints existen justo
             para el momento en que todavía no eligió modelo.
      2. Si no tiene base_url + api_key y ``allow_default=True``, se usa el
         LLM por defecto del backend (si ``GROQ_API_KEY`` está definida).
      3. Si no, ``reason="not_configured"``.

    Args:
        user_id: ID del usuario.
        allow_default: si es False, nunca se cae al LLM del sistema y una
            config sin modelo se devuelve tal cual (``model=""``).

    Returns:
        UserLLMConfig con la API key ya desencriptada.

    Raises:
        LLMConfigError: con ``reason`` ``"user_not_found"``,
            ``"not_configured"``, ``"decryption_failed"`` o ``"missing"`` (ver
            la clase). ``"initialization_failed"`` no sale de aquí: lo lanza
            ``build_langchain_model`` al construir el modelo.
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            # Un user_id que no existe es un bug o un ataque, no "usuario sin
            # configurar". Darle el default abriria la puerta a que cualquier
            # id desbordado reciba el LLM del sistema.
            raise LLMConfigError(f"Usuario {user_id} no encontrado", reason="user_not_found")

        if not user.llm_base_url or not user.encrypted_api_key:
            if allow_default:
                default = _load_system_default(user_id)
                if default is not None:
                    return default
            raise LLMConfigError(
                f"Usuario {user_id} no tiene configuracion de LLM. "
                "Completa el wizard (pasos 1 y 2) para usar tu propia API key, "
                "o configura GROQ_API_KEY en el backend para que la app use un "
                "LLM por defecto.",
                reason="not_configured",
            )

        # Desencriptar API key
        try:
            api_key = decrypt(user.encrypted_api_key)
        except EncryptionError as e:
            raise LLMConfigError(
                f"No se pudo desencriptar la API key: {e}",
                reason="decryption_failed",
            )

        if not user.llm_model and allow_default:
            # El endpoint y la key son del usuario, pero el modelo no.
            # Mezclar el modelo del default con el endpoint del usuario
            # genera un 400 (modelo Groq contra endpoint OpenAI, por
            # ejemplo). En el camino de chat no hay como completarlo:
            # error claro (``user_facing_message`` le dice que elija modelo).
            #
            # Con ``allow_default=False`` (wizard: step3 y available-models)
            # NO se chequea: la config parcial vuelve con ``model=""``. Si se
            # chequeara siempre, nadie podría terminar el wizard.
            raise LLMConfigError(
                f"Usuario {user_id} completo los pasos 1 y 2 pero no el 3. "
                "Elegi un modelo antes de continuar.",
                reason="missing",
            )

        return UserLLMConfig(
            user_id=user_id,
            base_url=user.llm_base_url,
            # Normalizado a "": el dataclass declara ``model: str`` y los
            # consumers del wizard no deben distinguir None vs vacio.
            model=user.llm_model or "",
            api_key=api_key,
            source="user",
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
    # 1. Verificar cache. Solo contiene configs del usuario (``source ==
    #    "user"``, ver el paso 4): el default del sistema se resuelve siempre
    #    fresco (ver `_load_system_default`).
    if not force_reload and user_id in _session_cache:
        cached_config, expires_at = _session_cache[user_id]
        if time.time() < expires_at:
            return _init_model(cached_config)

    # 2. Cargar config fresca desde DB (con fallback al default del sistema)
    config = load_user_llm_config(user_id)

    # 3. Observabilidad: el origen va al log, la key nunca. Sin esto no hay
    #    forma de saber cuanto trafico consume la cuenta del operador (#98).
    #    Ojo con el volumen: las configs del default no se cachean, así que
    #    esta línea sale en CADA request de un usuario que usa el default.
    _LOGGER.info(
        "llm_config resuelta: source=%s model=%s base_url=%s",
        config.source,
        config.model,
        config.base_url,
    )

    # 4. Cachear SOLO configs del usuario. El default del sistema queda fuera
    #    del cache por design (ver `_load_system_default`): si un usuario lo
    #    recibiera y despues completara el wizard, sin este guard seguiria
    #    viendo el default cacheado hasta que expirara el TTL de 300s.
    if config.source == "user":
        _session_cache[user_id] = (config, time.time() + _CACHE_TTL_SECONDS)

    # 5. Construir modelo
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
            raise LLMConfigError(f"Usuario {user_id} no encontrado", reason="user_not_found")

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
            raise LLMConfigError(f"Usuario {user_id} no encontrado", reason="user_not_found")
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
            raise LLMConfigError(f"Usuario {user_id} no encontrado", reason="user_not_found")
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
            raise LLMConfigError(f"Usuario {user_id} no encontrado", reason="user_not_found")
        user.llm_model = model
        db.commit()
    finally:
        db.close()
        clear_session_cache(user_id)
