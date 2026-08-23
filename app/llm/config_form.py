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

    # Pedir selección de modelo
    model_msg = await cl.AskUserMessage(
        content=f"**3/3** Selecciona el modelo (encontrados: {len(models)}):",
        timeout=180,
    ).send()

    model = model_msg["output"].strip()

    if model not in models:
        await cl.Message(
            content=f"❌ Modelo `{model}` no está en la lista. Intenta de nuevo."
        ).send()
        return

    # Guardar
    try:
        save_user_llm_config(
            user_id=user_id,
            base_url=base_url,
            model=model,
            api_key=api_key,
        )
        await cl.Message(
            content=f"✅ **Configuración guardada correctamente**\n\n"
            f"- **Proveedor**: `{base_url}`\n"
            f"- **Modelo**: `{model}`\n\n"
            f"Ahora puedes usar el asistente. Escribe tu consulta."
        ).send()
    except Exception as e:
        await cl.Message(
            content=f"❌ **Error al guardar:** {e}"
        ).send()


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
