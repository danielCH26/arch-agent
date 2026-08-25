"""
Formulario Chainlit para configurar el LLM del usuario.

Issue: #7 - HU12 Configuración de LLM

Usa una state machine en cl.user_session. El unico @cl.on_message vive en
app.py y delega a handle_config_flow cuando no es un comando global.
"""

import chainlit as cl
from typing import Optional

from app.core.llm_validator import (
    validate_llm_config,
    get_available_models,
    invalidate_cache,
    LLMValidationError,
)
from app.core.llm_loader import (
    save_user_llm_config,
    clear_session_cache,
    LLMConfigError,
)

_on_config_complete = None


def set_on_config_complete(callback):
    """Registra una función async (sin argumentos) a llamar cuando la
    configuración de LLM se guarda correctamente."""
    global _on_config_complete
    _on_config_complete = callback


# =============================================================================
# Lógica pura de filtrado (testeable sin Chainlit)
# =============================================================================

MAX_BUTTONS = 20  # Máximo de botones visibles para no saturar UI


def filter_models(models: list[str], filter_text: str) -> list[str]:
    """
    Filtra modelos por substring case-insensitive.

    Args:
        models: lista completa de modelos
        filter_text: texto a buscar (vacío = todos)

    Returns:
        Lista filtrada (preserva orden original)
    """
    if not filter_text or not filter_text.strip():
        return list(models)
    needle = filter_text.strip().lower()
    return [m for m in models if needle in m.lower()]


def split_visible_and_excess(
    filtered: list[str], max_visible: int = MAX_BUTTONS
) -> tuple[list[str], int]:
    """
    Divide los modelos filtrados en visibles (para botones) y el resto.

    Returns:
        (visible, excess_count)
    """
    if len(filtered) <= max_visible:
        return list(filtered), 0
    return list(filtered[:max_visible]), len(filtered) - max_visible


def match_model_exact(models: list[str], user_input: str) -> Optional[str]:
    """
    Busca match exacto (case-insensitive) de un modelo.

    Returns:
        El nombre real del modelo si hay match, None si no.
    """
    if not user_input:
        return None
    user_input = user_input.strip()
    # Match exacto (case-sensitive)
    if user_input in models:
        return user_input
    # Match case-insensitive
    for m in models:
        if m.lower() == user_input.lower():
            return m
    return None


def is_filter_refinement(user_input: str, models: list[str]) -> bool:
    """
    Determina si el input del usuario es un refinamiento de filtro
    (no es un nombre de modelo exacto pero matchea algunos).
    """
    if not user_input:
        return False
    user_input = user_input.strip().lower()
    # Si es match exacto, NO es refinamiento
    if user_input in [m.lower() for m in models]:
        return False
    # Si matchea algún modelo, ES refinamiento
    return any(user_input in m.lower() for m in models)


# =============================================================================
# Estado del form (state machine)
# =============================================================================


def get_form_state() -> dict:
    """Obtiene el estado actual del form desde la session."""
    state = cl.user_session.get("llm_form_state")
    if state is None:
        state = {"step": None, "base_url": None, "api_key": None, "models": None}
        cl.user_session.set("llm_form_state", state)
    return state


def set_form_state(**kwargs):
    """Actualiza el estado del form."""
    state = get_form_state()
    state.update(kwargs)
    cl.user_session.set("llm_form_state", state)


def clear_form_state():
    """Limpia el estado del form."""
    cl.user_session.set("llm_form_state", None)


# =============================================================================
# Flujo principal del formulario
# =============================================================================


async def render_config_form_if_needed(user_id: int) -> bool:
    """
    Si el usuario no tiene config LLM, muestra el formulario.

    Returns:
        True si la config ya existía (puede continuar al chat).
        False si se mostró el form (usuario debe completar).
    """
    from app.core.llm_loader import load_user_llm_config

    try:
        load_user_llm_config(user_id)
        return True  # Ya tiene config, puede continuar
    except LLMConfigError:
        # No tiene config → iniciar form
        clear_form_state()
        await _show_welcome_and_step1()
        return False


async def _show_welcome_and_step1() -> None:
    """Muestra bienvenida y pide URL base (paso 1/3)."""
    set_form_state(step="awaiting_base_url")
    await cl.Message(
        content=(
            "## 🔧 Configuración de LLM requerida\n\n"
            "Para usar el asistente, primero configura tu proveedor de LLM.\n\n"
            "**Proveedores soportados** (cualquier API OpenAI-compatible):\n"
            "- **OpenAI**: `https://api.openai.com/v1`\n"
            "- **Ollama** (local): `http://localhost:11434/v1`\n"
            "- **LM Studio** (local): `http://localhost:1234/v1`\n"
            "- **OpenRouter**: `https://openrouter.ai/api/v1`\n"
            "- **Groq**, **DeepSeek**, **Together AI**, etc.\n\n"
            "**Escribí la URL base del proveedor** (paso 1/3):"
        )
    ).send()


async def handle_config_flow(message: cl.Message):
    """Maneja el flujo del form según el estado actual."""
    state = get_form_state()
    step = state.get("step")

    user_input = message.content.strip()
    user_id = cl.user_session.get("user").metadata["user_id"] if cl.user_session.get("user") else None
    if not user_id:
        await cl.Message(content="❌ Error: usuario no identificado").send()
        return

    if step is None:
        # No hay form activo → mensaje normal del chat
        # Verificar si tiene config LLM
        await _handle_normal_chat_message(message, user_id)
        return

    if step == "awaiting_base_url":
        await _handle_base_url(user_input, user_id)
    elif step == "awaiting_api_key":
        await _handle_api_key(user_input, user_id, state["base_url"])
    elif step == "awaiting_model_filter":
        await _handle_model_filter(user_input, user_id, state)
    elif step == "awaiting_model_selection":
        await _handle_model_selection(user_input, user_id, state)
    elif step == "validating":
        # Mientras valida, ignorar input
        pass


async def _handle_normal_chat_message(message: cl.Message, user_id: int) -> None:
    """
    Maneja un mensaje normal del chat (fuera del form flow).

    Por ahora es un placeholder. En F08 se conecta al agente LangChain.
    """
    from app.core.llm_loader import load_user_llm_config, LLMConfigError

    # Verificar si tiene config
    try:
        config = load_user_llm_config(user_id)
        # Tiene config → el mensaje iría al agente (TODO F08)
        await cl.Message(
            content=(
                f"🤖 Recibí tu mensaje: \"{message.content}\"\n\n"
                f"Tu LLM configurado: `{config.model}`\n"
                f"Endpoint: `{config.base_url}`\n\n"
                f"⚠️ **Nota:** La integración con el agente LangChain es parte de F08 "
                f"(Sprint 2). Por ahora solo confirmo recepción de mensajes."
            )
        ).send()
    except LLMConfigError:
        # No tiene config → iniciar el form
        await cl.Message(
            content=(
                "⚠️ **Necesitás configurar tu LLM antes de usar el asistente.**\n\n"
                "Escribí la URL base del proveedor (ej: `https://api.openai.com/v1`):"
            )
        ).send()
        set_form_state(step="awaiting_base_url")


async def _handle_base_url(user_input: str, user_id: int) -> None:
    """Procesa URL base y pide API key."""
    base_url = user_input.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        await cl.Message(
            content="❌ URL inválida. Debe empezar con `http://` o `https://`.\n\n"
            "**Escribí la URL base nuevamente:**"
        ).send()
        return

    set_form_state(step="awaiting_api_key", base_url=base_url)
    await cl.Message(
        content=(
            f"✅ URL guardada: `{base_url}`\n\n"
            "**Escribí tu API Key** (paso 2/3) — se encriptará antes de guardar:"
        )
    ).send()


async def _handle_api_key(user_input: str, user_id: int, base_url: str) -> None:
    """Procesa API key, valida y pide modelo."""
    api_key = user_input.strip()
    if not api_key or len(api_key) < 5:
        await cl.Message(
            content="❌ API Key inválida (muy corta).\n\n"
            "**Escribí la API Key nuevamente:**"
        ).send()
        return

    await cl.Message(content="⏳ Validando conexión con el proveedor...").send()

    try:
        validate_llm_config(base_url, api_key)
    except LLMValidationError as e:
        await cl.Message(
            content=f"❌ **Error de validación:** {e}\n\n"
            "**Escribí la API Key nuevamente:**"
        ).send()
        return

    # Obtener modelos
    try:
        models = get_available_models(base_url, api_key, user_id)
    except LLMValidationError as e:
        await cl.Message(
            content=f"❌ **Error al listar modelos:** {e}\n\n"
            "**Escribí la API Key nuevamente:**"
        ).send()
        return

    if not models:
        await cl.Message(
            content="❌ El proveedor no devolvió modelos. Verifica la URL.\n\n"
            "**Escribí la API Key nuevamente:**"
        ).send()
        return

    # Pasar al paso 3
    set_form_state(step="awaiting_model_filter", api_key=api_key, models=models)
    await _show_model_filter_step(models, filter_text="", is_initial=True)


async def _show_model_filter_step(
    models: list[str],
    filter_text: str = "",
    is_initial: bool = False,
    user_id: Optional[int] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    """Muestra el paso 3 con filtro."""
    filtered = filter_models(models, filter_text)
    visible, excess = split_visible_and_excess(filtered)

    models_list = "\n".join([f"- `{m}`" for m in visible])

    extra_msg = ""
    if excess > 0:
        extra_msg = (
            f"\n\n_...y {excess} más._ "
            f"Refiná el filtro para ver menos."
        )

    actions = [
        cl.Action(
            name="select_model",
            payload={"model": m},
            label=m if len(m) <= 30 else m[:27] + "...",
            description=f"Seleccionar {m}",
        )
        for m in visible
    ]

    if is_initial:
        title = f"**Paso 3/3** Selecciona el modelo ({len(models)} disponibles)"
        prompt = "**Filtrá** los modelos (ej: `gpt`, `claude`) o **seleccioná uno de la lista:**"
    else:
        title = f"🔍 Filtrado por: `{filter_text}` ({len(filtered)} resultados)"
        prompt = "Filtrá más, o seleccioná un modelo:"

    await cl.Message(
        content=(
            f"{title}\n\n"
            f"{models_list}"
            f"{extra_msg}\n\n"
            f"{prompt}"
        ),
        actions=actions,
    ).send()


async def _handle_model_filter(user_input: str, user_id: int, state: dict) -> None:
    """Procesa input del paso 3 (filtro o selección)."""
    models = state["models"]

    # Intentar match exacto
    exact = match_model_exact(models, user_input)
    if exact:
        await _save_and_confirm(user_id, state["base_url"], exact, state["api_key"])
        clear_form_state()
        return

    # Es un refinamiento de filtro
    if is_filter_refinement(user_input, models):
        # Mostrar lista filtrada
        await _show_model_filter_step(
            models=models,
            filter_text=user_input.strip(),
            is_initial=False,
            user_id=user_id,
            base_url=state["base_url"],
            api_key=state["api_key"],
        )
        set_form_state(step="awaiting_model_filter")
        return

    # No match: pedir que filtre o escriba modelo correcto
    await cl.Message(
        content=f"❌ `{user_input}` no coincide con ningún modelo.\n\n"
        "Filtrá (ej: `gpt`) o escribí el nombre exacto del modelo:"
    ).send()


async def _handle_model_selection(user_input: str, user_id: int, state: dict) -> None:
    """Placeholder - actualmente se usa _handle_model_filter para todo."""
    await _handle_model_filter(user_input, user_id, state)


async def _save_and_confirm(
    user_id: int,
    base_url: str,
    model: str,
    api_key: str,
) -> None:
    """Guarda la config y muestra confirmación."""
    try:
        save_user_llm_config(
            user_id=user_id,
            base_url=base_url,
            model=model,
            api_key=api_key,
        )
        await cl.Message(
            content=(
                f"✅ **Configuración guardada correctamente**\n\n"
                f"- **Proveedor**: `{base_url}`\n"
                f"- **Modelo**: `{model}`"
            )
        ).send()
        if _on_config_complete:
            await _on_config_complete()
    except Exception as e:
        await cl.Message(
            content=f"❌ **Error al guardar:** {e}"
        ).send()


@cl.action_callback("select_model")
async def on_select_model(action: cl.Action):
    """Handler cuando el usuario hace clic en un botón de modelo."""
    model = action.payload.get("model")
    state = get_form_state()
    user_id = cl.user_session.get("user").metadata["user_id"] if cl.user_session.get("user") else None

    if not all([model, state.get("base_url"), state.get("api_key"), user_id]):
        await cl.Message(content="❌ Error: datos incompletos").send()
        return

    await _save_and_confirm(user_id, state["base_url"], model, state["api_key"])
    clear_form_state()


@cl.action_callback("configurar_llm")
async def on_configure_llm(action: cl.Action):
    """Handler cuando el usuario hace clic en 'Configurar LLM'."""
    user_id = action.payload.get("user_id")
    if not user_id:
        await cl.Message(content="❌ Error: usuario no identificado").send()
        return

    # Invalidar cache
    try:
        invalidate_cache(None, user_id)
        clear_session_cache(user_id)
    except Exception:
        pass

    clear_form_state()
    await _show_welcome_and_step1()


async def render_sidebar_settings(user_id: int) -> cl.Action:
    """Retorna el Action 'Configurar LLM' para usar dentro de un Message."""
    return cl.Action(
        name="configurar_llm",
        payload={"user_id": user_id},
        label="⚙️ Configurar LLM",
        description="Cambiar proveedor o modelo de LLM",
    )
