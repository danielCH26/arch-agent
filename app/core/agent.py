"""
LangChain agent runtime for Context7 MCP integration.

Exposes ``build_agent``, ``format_rag_context`` and ``run_agent`` — the three
helpers the ``/api/chat`` route uses after slice F11.4b swaps
``model.astream(prompt)`` for ``run_agent(...)``.

The module is intentionally lazy at the import boundary: it does NOT import
``langchain.agents.create_agent`` at top level so that pytest collection
succeeds even when the new wheels are not yet installed.

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

_LOGGER = logging.getLogger(__name__)

# Persona prompt that frames the agent as a software-architecture assistant.
# REQ-3 system-prompt composition. Kept here so both the route (for SSE
# preview) and ``build_agent`` consume the same constant.
ARCHITECT_PERSONA: str = (
    "Eres un asistente de arquitectura de software. "
    "Responde en español, de forma clara y accionable. "
    "Usa markdown (encabezados, negritas, tablas) libremente, pero NUNCA "
    "envuelvas la respuesta completa dentro de un bloque de codigo (```). "
    "Usa ``` unicamente para fragmentos de codigo real o diagramas ASCII "
    "puntuales, nunca para el mensaje entero."
)

# REQ-3 / design.md §9 risk 9 — the system prompt hint that prevents the
# agent from blindly invoking Context7 on every turn (cost + latency on
# small local models).
LIBRARY_HINT: str = (
    "Dispones de las herramientas ``resolve-library-id`` y ``query-docs`` "
    "para consultar documentacion de librerias externas (Context7). "
    "Invocalas SOLO cuando el usuario nombre una libreria concreta o "
    "pregunte por la API / uso de un paquete. Para preguntas sobre "
    "patrones de arquitectura cubiertos por el contexto RAG, responde "
    "directamente sin gastar herramientas."
)

# REQ-9 / ADR-010 §"Precedencia RAG ↔ Context7" — cap to keep tool result
# within budget on 8k-context models (Ollama llama3).
_TOOL_RESULT_MAX_CHARS: int = 4000


def format_rag_context(rag_documents: list[Any]) -> str:
    """Build the numbered RAG block that gets injected into the system prompt.

    Args:
        rag_documents: List of LangChain ``Document`` objects (or any object
            exposing ``page_content`` and ``metadata``). An empty list is
            permitted and yields a sentinel string so the agent knows the
            retrieval layer returned nothing relevant.

    Returns:
        A single string ready to be embedded into the agent system prompt.
        Includes a ``has_architect_pattern`` flag (callers can sniff it via
        ``run_agent`` to drop tools per REQ-8).
    """
    # NOTE: stub body — full implementation lands in slice F11.3a.
    raise NotImplementedError("format_rag_context lands in slice F11.3a")


def build_agent(
    model: Any,
    system_prompt: str,
    tools: list[Any] | None = None,
) -> Any:
    """Build a LangChain ``create_agent`` runtime.

    Args:
        model: ``BaseChatModel`` from ``build_langchain_model(user_id)``.
        system_prompt: Final composed prompt (persona + RAG block + hint).
        tools: Optional list of ``BaseTool``. When ``None`` or ``[]`` the
            agent runs in RAG-only mode (REQ-8).

    Returns:
        Compiled agent runtime (LangChain 1.x returns a ``CompiledStateGraph``;
        the exact type is irrelevant to callers, which only invoke
        ``astream_events``).
    """
    # NOTE: stub body — full implementation lands in slice F11.3a.
    raise NotImplementedError("build_agent lands in slice F11.3a")


async def run_agent(
    model: Any,
    message: str,
    *,
    callbacks: list[Any],
    rag_documents: list[Any] | None = None,
    user_id: int | None = None,
    project_id: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the agent and yield SSE-ready dicts.

    Yields dicts of shape ``{"event": str, "data": <json-safe>}``. The caller
    (``app/api/chat.py``) serializes each dict to the wire using
    ``json.dumps(..., ensure_ascii=False)``.

    Ordering guarantee:
      ``sources`` is yielded by the route BEFORE ``run_agent`` is invoked
      (it owns the RAG retrieval). ``run_agent`` yields ``tool_start`` /
      ``tool_end`` pairs (possibly zero), then ``token`` events, and ends
      with ``done``. On Context7 failure it yields exactly one
      ``degraded`` event before continuing.

    Args:
        model: ``BaseChatModel``.
        message: User prompt.
        callbacks: List of ``BaseCallbackHandler`` (SSE handler plus optional
            Langfuse handler).
        rag_documents: Pre-fetched RAG ``Document`` list (so the route keeps
            ownership of retrieval and can emit ``sources`` first).
        user_id: Optional user id; used by Langfuse trace-name metadata.
        project_id: Optional project id; ``None`` is recorded as ``"none"``.

    Yields:
        SSE-ready dicts.
    """
    # NOTE: stub body — full implementation lands in slice F11.3a.
    # The unreachable ``if False: yield`` makes this an async generator
    # function at runtime so the AsyncIterator[dict] type contract holds.
    raise NotImplementedError("run_agent lands in slice F11.3a")
    if False:  # pragma: no cover
        yield {}  # type: ignore[unreachable]
