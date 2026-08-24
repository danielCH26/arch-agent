"""
Formulario Chainlit para configurar el LLM del usuario.

Issue: #7 - HU12 Configuración de LLM
"""

import chainlit as cl
from typing import Optional

from app.core.llm_validator import (
    validate_llm_config,
    get_available_models,
    invalidate_cache,
    LLMValidationError,
)


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
from app.core.llm_loader import (
    save_user_llm_config,
    clear_session_cache,
    LLMConfigError,
)


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
        # No tiene config → mostrar form
        await _show_initial_form()
        return False


async def _show_initial_form() -> None:
    """Muestra el formulario inicial para configurar LLM."""
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
            "Por favor completa los siguientes datos:"
        )
    ).send()

    # Pedir URL base
    base_url_msg = await cl.AskUserMessage(
        content="**1/3** URL base del proveedor (ej: `https://api.openai.com/v1`):",
        timeout=180,
    ).send()

    base_url = base_url_msg["output"].strip().rstrip("/")

    # Pedir API Key
    api_key_msg = await cl.AskUserMessage(
        content="**2/3** API Key (se encriptará antes de guardar):",
        timeout=180,
    ).send()

    api_key = api_key_msg["output"].strip()

    # Validar
    await cl.Message(content="⏳ Validando conexión con el proveedor...").send()

    try:
        validate_llm_config(base_url, api_key)
    except LLMValidationError as e:
        await cl.Message(
            content=f"❌ **Error de validación:** {e}\n\n"
            "Por favor intenta de nuevo con el comando `/configurar_llm`."
        ).send()
        return

    # Obtener modelos disponibles
    user_id = cl.user_session.get("user").metadata["user_id"]
    try:
        models = get_available_models(base_url, api_key, user_id)
    except LLMValidationError as e:
        await cl.Message(
            content=f"❌ **Error al listar modelos:** {e}"
        ).send()
        return

    if not models:
        await cl.Message(
            content="❌ El proveedor no devolvió modelos. Verifica la URL."
        ).send()
        return

    # Paso 3: Selector de modelo con filtro dinámico
    await _select_model_with_filter(models, base_url, api_key, user_id)


async def _select_model_with_filter(
    models: list[str],
    base_url: str,
    api_key: str,
    user_id: int,
    attempts_left: int = 2,
) -> None:
    """
    Paso 3 con filtro dinámico.

    Pide un texto para filtrar (ej: "gpt"), muestra los modelos que
    coincidan como botones + lista de texto. Si no hay match, permite
    reintentar hasta `attempts_left` veces.
    """
    # 1. Pedir filtro
    filter_msg = await cl.AskUserMessage(
        content=(
            "**3/3** Selecciona el modelo\n\n"
            f"TOTAL: {len(models)} modelos disponibles.\n\n"
            "Escribí un texto para filtrar (ej: `gpt`, `claude`, `embed`)\n"
            "o dejá vacío para ver todos."
        ),
        timeout=180,
    ).send()
    filter_text = filter_msg["output"]

    # 2. Filtrar (lógica pura)
    filtered = filter_models(models, filter_text)

    # 3. Validar filtro
    if not filtered:
        await cl.Message(
            content=f"❌ No hay modelos que contengan `{filter_text.strip()}`."
        ).send()
        if attempts_left > 0:
            return await _select_model_with_filter(
                models, base_url, api_key, user_id, attempts_left - 1
            )
        else:
            await cl.Message(
                content="Se acabaron los intentos. Empezá de nuevo con `/configurar_llm`."
            ).send()
            return

    # 4. Renderizar resultados
    visible, excess = split_visible_and_excess(filtered)
    await _render_models_view(
        models=models,
        filtered=filtered,
        visible=visible,
        excess=excess,
        filter_text=filter_text.strip(),
        base_url=base_url,
        api_key=api_key,
        user_id=user_id,
        is_refinement=False,
    )


async def _render_models_view(
    models: list[str],
    filtered: list[str],
    visible: list[str],
    excess: int,
    filter_text: str,
    base_url: str,
    api_key: str,
    user_id: int,
    is_refinement: bool,
) -> None:
    """
    Renderiza la vista del selector (botones + lista) y maneja la respuesta.

    Args:
        is_refinement: si True, no vuelve a pedir filtro (estamos refinando)
    """
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
            payload={"model": m, "base_url": base_url, "api_key": api_key},
            label=m if len(m) <= 30 else m[:27] + "...",
            description=f"Seleccionar {m}",
        )
        for m in visible
    ]

    if is_refinement:
        title = f"**Refinando filtro: `{filter_text}`** ({len(filtered)} resultados)"
        prompt = "✏️ Selecciona un botón o escribí el nombre exacto:"
    else:
        if filter_text:
            title = f"**🔍 Filtrado por: `{filter_text}`** ({len(filtered)} resultados)"
        else:
            title = f"**Sin filtro** ({len(filtered)} modelos)"
        prompt = (
            "✏️ Escribí el nombre exacto (o un nuevo texto para filtrar):"
        )

    await cl.Message(
        content=(
            f"{title}\n\n"
            f"{models_list}"
            f"{extra_msg}\n\n"
            "**Hacé clic en un botón** para seleccionar."
        ),
        actions=actions,
    ).send()

    # Input del usuario
    input_msg = await cl.AskUserMessage(content=prompt, timeout=180).send()
    response = input_msg["output"].strip()

    # Decidir qué hacer
    if not response:
        await cl.Message(content="❌ No escribiste nada.").send()
        return

    # 1. Match exacto (case-insensitive)
    exact_match = match_model_exact(models, response)
    if exact_match:
        await _save_and_confirm(user_id, base_url, exact_match, api_key)
        return

    # 2. Es un refinamiento de filtro?
    if is_filter_refinement(response, models):
        new_filtered = filter_models(models, response)
        new_visible, new_excess = split_visible_and_excess(new_filtered)
        await cl.Message(
            content=f"🔍 Refinando filtro a `{response}` ({len(new_filtered)} resultados)"
        ).send()
        await _render_models_view(
            models=models,
            filtered=new_filtered,
            visible=new_visible,
            excess=new_excess,
            filter_text=response,
            base_url=base_url,
            api_key=api_key,
            user_id=user_id,
            is_refinement=True,
        )
        return

    # 3. No match
    await cl.Message(
        content=f"❌ `{response}` no coincide con ningún modelo disponible."
    ).send()
    if not is_refinement:
        # Volver a pedir el filtro inicial
        return await _select_model_with_filter(
            models, base_url, api_key, user_id, attempts_left=1
        )


async def _save_and_confirm(
    user_id: int,
    base_url: str,
    model: str,
    api_key: str,
) -> None:
    """Guarda la config y muestra confirmación. Usado tanto por input manual como por botón."""
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
                f"- **Modelo**: `{model}`\n\n"
                f"Ahora puedes usar el asistente. Escribe tu consulta."
            )
        ).send()
    except Exception as e:
        await cl.Message(
            content=f"❌ **Error al guardar:** {e}"
        ).send()


@cl.action_callback("select_model")
async def on_select_model(action: cl.Action):
    """Handler cuando el usuario hace clic en un botón de modelo."""
    model = action.payload.get("model")
    base_url = action.payload.get("base_url")
    api_key = action.payload.get("api_key")
    user_id = cl.user_session.get("user").metadata["user_id"] if cl.user_session.get("user") else None

    if not all([model, base_url, api_key, user_id]):
        await cl.Message(content="❌ Error: datos incompletos").send()
        return

    await _save_and_confirm(user_id, base_url, model, api_key)


async def render_sidebar_settings(user_id: int) -> None:
    """Renderiza el botón 'Configurar LLM' en el sidebar."""
    # Chainlit usa cl.Action para acciones en sidebar
    await cl.Action(
        name="configurar_llm",
        payload={"user_id": user_id},
        label="⚙️ Configurar LLM",
        description="Cambiar proveedor o modelo de LLM",
    ).send()


@cl.action_callback("configurar_llm")
async def on_configure_llm(action: cl.Action):
    """Handler cuando el usuario hace clic en 'Configurar LLM'."""
    user_id = action.payload.get("user_id")
    if not user_id:
        await cl.Message(content="❌ Error: usuario no identificado").send()
        return

    # Invalidar cache (por si cambió el proveedor)
    try:
        invalidate_cache(None, user_id)  # engram_client=None = best-effort
        clear_session_cache(user_id)
    except Exception:
        pass

    await cl.Message(
        content="## ⚙️ Reconfiguración de LLM\n\n"
        "Vamos a actualizar tu configuración:"
    ).send()

    await _show_initial_form()
