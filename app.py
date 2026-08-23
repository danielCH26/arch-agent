"""
app.py — Entrypoint Chainlit del Asistente de Arquitectura (F01).

Este archivo es el esqueleto minimo necesario para que el container
`app` arranque y tenga un chat funcional.

La logica completa del agente (RAG, elicitación, propuestas, etc.)
se implementa en issues posteriores (F05..F15).
"""

import os

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
# Hooks de Chainlit
# ============================================================================
@cl.on_chat_start
async def start() -> None:
    """Saluda cuando el usuario abre el chat."""
    await cl.Message(
        content=(
            f"Hola, soy **{APP_NAME}**.\n\n"
            "Por ahora estoy en modo **Sprint 1 -- F01 (Docker Compose)**. "
            "La logica completa del agente (RAG, elicitación, propuestas, "
            "diagramas, trade-offs) llega en los siguientes issues.\n\n"
            "Si puedes leer este mensaje, significa que:\n"
            "- OK El container `app` esta corriendo\n"
            "- OK La red Docker conecta con el resto de servicios\n"
            "- OK Las variables de entorno se cargaron correctamente\n\n"
            "**Proximos pasos:** revisa http://localhost:3000 (Langfuse UI) "
            "y la base `asistente_db` en postgres-app:5432."
        )
    ).send()


@cl.on_message
async def main(message: cl.Message) -> None:
    """Echo basico -- el agente real se conecta en F05..F15."""
    await cl.Message(
        content=(
            f"Recibido: _{message.content}_\n\n"
            "El agente conversacional se implementa en issues posteriores. "
            "Por ahora esto es un smoke test del entorno Docker."
        )
    ).send()
