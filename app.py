"""
app.py — Entrypoint Chainlit del Asistente de Arquitectura (F01).

Este archivo es el esqueleto minimo necesario para que el container
`app` arranque, exponga /health y tenga un chat funcional.

La logica completa del agente (RAG, elicitación, propuestas, etc.)
se implementa en issues posteriores (F05..F15).
"""

import os
from datetime import datetime, timezone

import chainlit as cl


# ============================================================================
# Configuracion basica (lee de variables de entorno / .env)
# ============================================================================
APP_NAME = os.getenv("APP_NAME", "Asistente de Arquitectura")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://asistente:asistente@postgres-app:5432/asistente_db")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "http://langfuse-web:3000")
ENGRAM_PROJECT = os.getenv("ENGRAM_PROJECT", "asistente-arquitectura")


# ============================================================================
# Endpoint /health para que el healthcheck del Dockerfile y de Docker Compose
# puedan verificar que el servicio esta vivo.
# ============================================================================
@cl.http_endpoint(method=["GET"], path="/health")
async def health() -> dict:
    """Devuelve el estado del servicio."""
    return {
        "status": "ok",
        "service": APP_NAME,
        "time": datetime.now(timezone.utc).isoformat(),
        "llm_model": LLM_MODEL,
        "langfuse": LANGFUSE_BASE_URL,
        "engram_project": ENGRAM_PROJECT,
    }


# ============================================================================
# Hooks de Chainlit
# ============================================================================
@cl.on_chat_start
async def start() -> None:
    """Saluda cuando el usuario abre el chat."""
    await cl.Message(
        content=(
            f"👋 Hola, soy **{APP_NAME}**.\n\n"
            "Por ahora estoy en modo **Sprint 1 — F01 (Docker Compose)**. "
            "La logica completa del agente (RAG, elicitación, propuestas, "
            "diagramas, trade-offs) llega en los siguientes issues.\n\n"
            "Si puedes leer este mensaje, significa que:\n"
            "- ✅ El container `app` esta corriendo\n"
            "- ✅ La red Docker conecta con el resto de servicios\n"
            "- ✅ Las variables de entorno se cargaron correctamente\n\n"
            "**Proximos pasos:** revisa http://localhost:3000 (Langfuse UI) "
            "y la base `asistente_db` en postgres-app:5432."
        )
    ).send()


@cl.on_message
async def main(message: cl.Message) -> None:
    """Echo basico — el agente real se conecta en F05..F15."""
    await cl.Message(
        content=(
            f"Recibido: _{message.content}_\n\n"
            "🚧 El agente conversacional se implementa en issues posteriores. "
            "Por ahora esto es un smoke test del entorno Docker."
        )
    ).send()
