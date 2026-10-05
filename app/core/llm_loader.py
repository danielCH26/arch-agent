"""
Carga de configuración LLM del usuario y construcción del modelo LangChain.

Issue: #7 - HU12 Configuración de LLM
"""

import logging
import os
import re
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

    Args:
        user_id: ID del usuario.
        allow_default: si True (default), cae al LLM del sistema cuando el
            usuario no tiene config completa. Si False, propaga
            ``LLMConfigError(reason="not_configured")`` en su lugar. Los
            endpoints del wizard (step3, available-models) lo pasan en False
            porque necesitan que el usuario complete los pasos antes de
            continuar; el camino de chat lo deja en True para que un usuario
            nuevo pueda hablar sin tener que configurar nada.

    Returns:
        UserLLMConfig con la API key ya desencriptada y el model (puede
        ser vacio si el user no completo todavia el step3 del wizard).

    Raises:
        LLMConfigError: si el usuario no tiene config o está corrupta.
            El atributo ``reason`` distingue los modos:
              - ``"not_configured"``: no hay config del usuario y (si
                ``allow_default=False``) tampoco se pidio fallback al sistema.
            ``"- decryption_failed"``: la API key en DB no se puede desencriptar.
            ``"- missing"``: hay base_url + api_key del usuario pero falta el
                modelo. Antes del fix B3 se completaba con el del default, lo
                que mezclaba el endpoint del usuario con un id de modelo que
                ese provider no reconoce (400 silencioso al primer request).
            ``"- initialization_failed"``: error al construir el chat model.

    Nota historica: antes esta funcion requeria que `llm_model` estuviera
    seteado, pero eso rompe el flujo del wizard: despues de step2 el
    user tiene base_url + api_key guardadas pero todavia no eligio
    modelo, asi que available-models (que se llama justo despues de
    step2) falla con 404. Por eso ahora solo exigimos base_url +
    api_key. La validacion de model vacio se hace mas adelante (en
    build_langchain_model, que es donde realmente importa).

    Desde #98, si al usuario le falta cualquiera de los tres campos, se intenta
    el LLM por defecto del backend. El default es el ULTIMO recurso: solo aplica
    cuando la config del usuario esta incompleta, nunca la pisa.
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            # Un user_id que no existe es un bug o un ataque, no "usuario sin
            # configurar". Darle el default abriria la puerta a que cualquier
            # id desbordado reciba el LLM del sistema.
            raise LLMConfigError(f"Usuario {user_id} no encontrado")

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

        if not user.llm_model:
            # El endpoint y la key son del usuario, pero el modelo no.
            # Mezclar el modelo del default con el endpoint del usuario
            # genera un 400 (modelo Groq contra endpoint OpenAI, por
            # ejemplo). Mejor pedir que complete el paso 3 del wizard.
            # Esta validacion corre SIEMPRE, independiente de
            # ``allow_default``: el default solo cubre el caso "no config",
            # nunca "config parcial del usuario".
            raise LLMConfigError(
                f"Usuario {user_id} completo los pasos 1 y 2 pero no el 3. "
                "Elegi un modelo antes de continuar.",
                reason="missing",
            )

        return UserLLMConfig(
            user_id=user_id,
            base_url=user.llm_base_url,
            model=user.llm_model,
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
    import time

    # 1. Verificar cache. El default del sistema se resuelve SIEMPRE fresco
    #    (ver `_load_system_default`): cacheado por user_id, un usuario que lo
    #    recibiera y despues completara el wizard seguiria viendo el default
    #    hasta que expirara el TTL.
    if not force_reload and user_id in _session_cache:
        cached_config, expires_at = _session_cache[user_id]
        if time.time() < expires_at:
            if cached_config.source == "system_default":
                fresh = _load_system_default(user_id)
                if fresh is not None:
                    return _init_model(fresh)
            return _init_model(cached_config)

    # 2. Cargar config fresca desde DB (con fallback al default del sistema)
    config = load_user_llm_config(user_id)

    # 3. Observabilidad: el origen va al log, la key nunca. Sin esto no hay
    #    forma de saber cuanto trafico consume la cuenta del operador (#98).
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

    try:
        return _build_chat_model(
            config.model,
            config.base_url,
            config.api_key,
            DEFAULT_LLM_TEMPERATURE,
        )
    except Exception as e:
        raise LLMConfigError(
            f"No se pudo inicializar el modelo {config.model}: {e}",
            reason="initialization_failed",
        )


def _build_chat_model(
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
) -> BaseChatModel:
    """Construye un chat model OpenAI-compatible, omitiendo temperature para la serie o*.

    Antes este codigo vivia inline en ``_init_model`` y se duplicaba en
    ``evals/runner.py:construir_modelo``. Centralizarlo evita el bug que
    sufrio el harness: si el runner duplicaba la construccion sin respetar
    la omision de temperature, ``openai/o1-mini`` se construia con
    ``temperature=0.0`` y el provider devolvia 400 al primer token.

    Args:
        model: nombre del modelo (con o sin prefijo ``provider/``).
        base_url: endpoint del provider OpenAI-compatible.
        api_key: API key en texto plano (ya desencriptada).
        temperature: valor a pasar al provider si el modelo lo admite.

    Returns:
        Instancia de ``BaseChatModel`` lista para ``invoke`` / ``astream``.
    """
    kwargs: dict = {
        "model": model,
        "model_provider": "openai",  # Cualquier API OpenAI-compatible
        "base_url": base_url,
        "api_key": api_key,
    }
    # Solo se manda `temperature` si el modelo lo admite. Omitirlo no es un
    # descuido: es lo unico que hace que la serie `o*` funcione, porque su
    # unico valor valido es 1 y mandarle otro produce un 400 en request time.
    if _acepta_temperature(model):
        kwargs["temperature"] = temperature

    return init_chat_model(**kwargs)


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
