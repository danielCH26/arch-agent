"""
LangChain agent runtime for Context7 MCP integration.

Exposes ``build_agent``, ``format_rag_context`` and ``run_agent`` — the three
helpers the ``/api/chat`` route uses after slice F11.4b swaps
``model.astream(prompt)`` for ``run_agent(...)``.

The module is lazy at the import boundary: it does NOT import
``langchain.agents.create_agent`` at top level so that pytest collection
succeeds even when the new wheels are not yet installed.

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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

# Cap on RAG documents injected into the system prompt. REQ-8 / risk 5.
_RAG_DOCS_CAP: int = 5

# Truncation marker used when a tool result exceeds the budget (ADR-010).
_TOOL_RESULT_TRUNCATION_MARKER: str = (
    "... [truncado, ver Langfuse trace para el resultado completo]"
)


def _coerce_documents(rag_documents: list[Any] | None) -> list[Any]:
    """Normalize the input list and apply the k≤5 cap."""
    docs = list(rag_documents or [])[:_RAG_DOCS_CAP]
    return docs


def _has_architect_pattern(rag_documents: list[Any]) -> bool:
    """True if any document is tagged as an architect pattern (REQ-8)."""
    for doc in rag_documents:
        metadata = getattr(doc, "metadata", None)
        if metadata is None and isinstance(doc, dict):
            metadata = doc.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("source_type") == "architect_pattern":
                return True
    return False


def format_rag_context(rag_documents: list[Any]) -> str:
    """Build the numbered RAG block that gets injected into the system prompt.

    Args:
        rag_documents: List of LangChain ``Document`` objects (or any object
            exposing ``page_content`` and ``metadata``). An empty list is
            permitted and yields a sentinel string so the agent knows the
            retrieval layer returned nothing relevant.

    Returns:
        A single string ready to be embedded into the agent system prompt.
        REQ-8 callers (``run_agent``) detect architect-pattern docs via
        ``_has_architect_pattern(rag_documents)`` and drop tools accordingly.
    """
    docs = _coerce_documents(rag_documents)
    if not docs:
        return "(sin contexto RAG)"

    blocks: list[str] = []
    for index, doc in enumerate(docs, start=1):
        page = getattr(doc, "page_content", "")
        metadata = getattr(doc, "metadata", None) or {}
        source = (
            metadata.get("pattern_name")
            or metadata.get("filename")
            or metadata.get("source_type")
            or "fuente"
        )
        blocks.append(f"[{index}] {source}\n{page}")

    return "\n\n".join(blocks)


def _build_system_prompt(rag_documents: list[Any]) -> str:
    """Compose the final system prompt from persona + RAG block + hint."""
    return f"{ARCHITECT_PERSONA}\n\nContexto RAG recuperado:\n{format_rag_context(rag_documents)}\n\n{LIBRARY_HINT}"


def _create_agent(model: Any, tools: list[Any], system_prompt: str) -> Any:
    """Lazy import of ``langchain.agents.create_agent``."""
    from langchain.agents import create_agent

    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


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
    tool_list = list(tools or [])
    return _create_agent(model=model, tools=tool_list, system_prompt=system_prompt)


def _truncate_tool_result(output: Any) -> tuple[str, int]:
    """Truncate a tool result to ``_TOOL_RESULT_MAX_CHARS`` with a marker.

    Returns:
        (truncated_text, length_used). ``length_used`` is the byte length of
        the *truncated* payload so SSE consumers see the actual on-wire size.
    """
    if isinstance(output, str):
        text = output
    else:
        try:
            text = json.dumps(output, ensure_ascii=False)
        except Exception:
            text = str(output)

    if len(text) <= _TOOL_RESULT_MAX_CHARS:
        return text, len(text.encode("utf-8"))

    truncated = text[: _TOOL_RESULT_MAX_CHARS - len(_TOOL_RESULT_TRUNCATION_MARKER)]
    truncated = truncated + _TOOL_RESULT_TRUNCATION_MARKER
    return truncated, len(truncated.encode("utf-8"))


def _extract_token_text(chunk: Any) -> str | None:
    """Pull the textual token from a chat-model stream chunk."""
    # LangChain >=0.3 emits ``AIMessageChunk`` with ``content`` as either a
    # plain string or a list of content-part dicts. We only forward string
    # content (text tokens); tool-call deltas are surfaced via tool events.
    content = getattr(chunk, "content", None)
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
        if text_parts:
            return "".join(text_parts)
    return None


async def _try_get_context7_tools() -> tuple[list[Any], dict[str, Any] | None]:
    """Fetch Context7 tools; on failure return ``([], degraded_event_dict)``.

    The route is responsible for emitting the ``degraded`` SSE event when
    ``degraded_event_dict`` is not ``None``. ``run_agent`` always continues
    with an empty tools list so the chat response still streams (REQ-6).
    """
    try:
        from app.core.context7_mcp import get_context7_tools

        tools = await get_context7_tools()
        return tools, None
    except Exception as e:
        reason = getattr(e, "reason", "context7_unavailable") or "context7_unavailable"
        message = str(e) or "Context7 unavailable"
        _LOGGER.warning("Context7 unavailable, degrading to RAG-only: %s", message)
        return [], {
            "source": "context7",
            "reason": reason,
            "fallback": "rag_only",
            "message": message,
        }


async def _astream_agent(
    agent: Any,
    message: str,
    callbacks: list[Any],
    *,
    user_id: int | None = None,
    project_id: int | None = None,
    model_name: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive ``agent.astream_events`` and yield SSE-ready dicts.

    Token events come from ``on_chat_model_stream`` chunks; tool events come
    from ``on_tool_start`` / ``on_tool_end``. We don't relay
    ``on_chat_model_end`` (the route emits ``done``) nor ``on_chain_*``
    (internal LangChain scaffolding).

    ``user_id`` / ``project_id`` / ``model_name`` flow into the run config
    metadata so Langfuse can label the trace (REQ-5 / SCN-7).
    """
    config: dict[str, Any] = {}
    if callbacks:
        config["callbacks"] = callbacks

    metadata: dict[str, Any] = {}
    if user_id is not None:
        metadata["user_id"] = user_id
    metadata["project_id"] = "none" if project_id is None else str(project_id)
    if model_name:
        metadata["model"] = model_name
    if metadata:
        config["metadata"] = metadata
        # Langfuse picks up ``run_name`` from the config; default to a
        # human-readable identifier for cross-trace filtering.
        config.setdefault(
            "run_name",
            f"chat/user-{user_id if user_id is not None else 'anon'}/project-{metadata['project_id']}",
        )

    try:
        event_iter = agent.astream_events(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
            version="v2",
        )
    except Exception as e:
        _LOGGER.exception("agent.astream_events failed: %s", e)
        yield {"event": "error", "data": str(e)}
        return

    async for raw in event_iter:
        ev_type = raw.get("event")
        if ev_type == "on_chat_model_stream":
            chunk = raw.get("data", {}).get("chunk")
            text = _extract_token_text(chunk)
            if text:
                yield {"event": "token", "data": text}
        elif ev_type == "on_tool_start":
            name = raw.get("name") or (raw.get("data", {}).get("input") or {}).get("name") or "tool"
            yield {"event": "tool_start", "data": {"tool": name}}
        elif ev_type == "on_tool_end":
            name = raw.get("name") or "tool"
            output = raw.get("data", {}).get("output")
            _, length = _truncate_tool_result(output)
            yield {
                "event": "tool_end",
                "data": {"tool": name, "result_length": length, "status": "ok"},
            }
        # All other events (on_chain_*, on_chat_model_end, on_prompt_*, etc.)
        # are intentionally not surfaced to the SSE channel.
        continue


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
      ``degraded`` event before continuing with RAG-only tokens.

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
    docs = _coerce_documents(rag_documents)
    system_prompt = _build_system_prompt(docs)

    # REQ-8 precedence rule: when RAG already covers an architect pattern,
    # skip the Context7 tool fetch entirely (cost + latency on small models).
    if _has_architect_pattern(docs):
        tools: list[Any] = []
        _LOGGER.info(
            "RAG contains an architect_pattern; skipping Context7 tool fetch "
            "(user_id=%s, project_id=%s)",
            user_id,
            project_id,
        )
    else:
        tools, degraded = await _try_get_context7_tools()
        if degraded is not None:
            # REQ-6: emit exactly one degraded event before any token.
            yield {"event": "degraded", "data": degraded}

    agent = build_agent(model=model, system_prompt=system_prompt, tools=tools)

    model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
    if not isinstance(model_name, str):
        model_name = None

    # Forward each event from the agent stream to the SSE channel.
    async for sse_dict in _astream_agent(
        agent,
        message,
        callbacks,
        user_id=user_id,
        project_id=project_id,
        model_name=model_name,
    ):
        yield sse_dict

    # ``done`` is the last event on success — design.md §5.2 ordering rule.
    yield {"event": "done", "data": None}


# ---------------------------------------------------------------------------
# Internals exposed for tests (NOT part of the public API surface)
# ---------------------------------------------------------------------------


__all__ = [
    "ARCHITECT_PERSONA",
    "LIBRARY_HINT",
    "_TOOL_RESULT_MAX_CHARS",
    "build_agent",
    "format_rag_context",
    "run_agent",
]
