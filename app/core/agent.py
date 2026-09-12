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
import base64
import json
import logging
import os
import uuid
from typing import Any, AsyncIterator

from app.core.attachment_tokens import _ensure_uploads_dir, sign_attachment_token
from app.core.mermaid_validator import extract_mermaid_block, validate_mermaid

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

# REQ-PMCP-1 / ADR-013 — instructs the model to render each fenced
# ``mermaid`` block it emits via ``puppeteer_screenshot``. The hard cap
# (one render per turn) keeps the SSE channel quiet and matches the
# pre-``done`` transaction semantics.
# F09: se agrega guia de que tipo de diagrama Mermaid usar segun lo que
# pida el usuario (flujo / componentes / secuencia).
DIAGRAM_HINT: str = (
    "Dispones de la herramienta ``puppeteer_screenshot`` para renderizar "
    "diagramas Mermaid a PNG. Elige el tipo de diagrama Mermaid segun lo "
    "que el usuario pida ver:\n"
    "- flujo de proceso -> ``flowchart`` o ``graph``\n"
    "- componentes/arquitectura -> ``flowchart`` con subgraphs por "
    "componente\n"
    "- interaccion entre servicios en el tiempo -> ``sequenceDiagram``\n"
    "Despues de emitir un bloque ```mermaid ...```, invocala exactamente "
    "UNA vez por turno con el bloque completo para que el frontend pueda "
    "mostrar la imagen inline. NO uses ``puppeteer_screenshot`` para nada "
    "que no sea un diagrama Mermaid, y NO invoques otras herramientas de "
    "Puppeteer: la superficie de herramientas esta limitada a un unico "
    "render de screenshot. IMPORTANTE: nunca escribas vos mismo una "
    "etiqueta markdown de imagen (``![...](...)``) ni ningun data-URI "
    "base64 en tu respuesta -- el sistema ya muestra la imagen "
    "renderizada automaticamente despues de que invoques la tool; "
    "escribir la etiqueta vos mismo produce una imagen rota."
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


def _build_system_prompt(rag_documents: list[Any], puppeteer_available: bool = True) -> str:
    """Compose the final system prompt from persona + RAG block + hints."""
    hints = LIBRARY_HINT
    if puppeteer_available:
        hints = f"{hints}\n\n{DIAGRAM_HINT}"
    return (
        f"{ARCHITECT_PERSONA}\n\n"
        f"Contexto RAG recuperado:\n{format_rag_context(rag_documents)}\n\n"
        f"{hints}"
    )


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
    """Fetch Context7 tools; on failure return ``([], degraded_event_dict)``."""
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


async def _try_get_puppeteer_tools(
    user_id: int | None = None,
) -> tuple[list[Any], dict[str, Any] | None]:
    """Fetch Puppeteer tools; on failure return ``([], degraded_event_dict)``."""
    try:
        from app.core.puppeteer_mcp import (
            PuppeteerUnavailable,
            _check_rate_limit,
            get_puppeteer_tools,
        )

        _check_rate_limit(user_id)
        tools = await get_puppeteer_tools()
        return tools, None
    except PuppeteerUnavailable as e:
        reason = getattr(e, "reason", "puppeteer_unavailable") or "puppeteer_unavailable"
        message = str(e) or "Puppeteer unavailable"
        _LOGGER.warning(
            "Puppeteer unavailable for user_id=%s; degrading: %s",
            user_id,
            message,
        )
        return [], {
            "source": "puppeteer",
            "reason": reason,
            "fallback": "text_only",
            "message": message,
        }
    except Exception as e:  # pragma: no cover — defensive belt-and-braces
        _LOGGER.warning(
            "Puppeteer tool fetch crashed for user_id=%s: %s", user_id, e
        )
        return [], {
            "source": "puppeteer",
            "reason": "puppeteer_unavailable",
            "fallback": "text_only",
            "message": str(e),
        }


_MERMAID_RENDER_DELAY_SECONDS: float = 3.0


def _build_mermaid_preview_html(mermaid_code: str) -> str:
    """Pagina HTML autocontenida que renderiza un bloque Mermaid via
    mermaid.js (CDN).

    FIX (bug: "el diagrama sale en blanco"): el backend navega el browser
    de Puppeteer a esta pagina ANTES de tomar el screenshot. Sin este
    paso, ``puppeteer_screenshot`` capturaba lo que estuviera cargado en
    ese momento -- por defecto, una pagina en blanco -- porque el modelo
    nunca tiene acceso a ``puppeteer_navigate`` (REQ-PMCP-2 allow-list).
    Esta funcion se usa SOLO server-side, nunca es invocada por el LLM.
    """
    import html as _html

    escaped = _html.escape(mermaid_code)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<script src='https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js'></script>"
        "<style>body{margin:0;padding:16px;background:#fff;}</style>"
        "</head><body><pre class='mermaid'>" + escaped + "</pre>"
        "<script>"
        # ``startOnLoad`` depende de que el DOM llegue a
        # DOMContentLoaded/load exactamente cuando mermaid espera, lo cual
        # es fragil dentro de una pagina ``data:`` navegada por Puppeteer.
        # Llamamos a ``mermaid.run()`` a mano (API recomendada en mermaid
        # v10+) e imprimimos en consola cuando termina, para poder
        # diagnosticar via logs si el render nunca llega a completarse.
        "mermaid.initialize({startOnLoad:false});"
        "mermaid.run({querySelector:'.mermaid'})"
        ".then(()=>{document.title='mermaid-rendered';})"
        ".catch((e)=>{document.title='mermaid-error';console.error(e);});"
        "</script>"
        "</body></html>"
    )


def _mermaid_html_to_data_url(html: str) -> str:
    """Codifica el HTML del preview como ``data:text/html;base64,...``
    para navegar sin depender de un servidor estatico adicional."""
    encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f"data:text/html;base64,{encoded}"


def _wrap_screenshot_tool_for_groq_compat(
    tool: Any,
    attachment_sink: dict[str, Any],
    *,
    navigate_coroutine: Any | None = None,
    response_parts: list[str] | None = None,
) -> None:
    """Parcha ``puppeteer_screenshot`` para que el content que vuelve al
    modelo sea siempre un string plano (Groq/proveedores OpenAI-compatible
    rechazan bloques de imagen en mensajes de rol tool: ``messages[N].content
    must be a string``), y guarda el PNG real en disco para que
    ``_astream_agent`` pueda emitir ``event: attachment`` después.

    FIX 1 (bug: "aparece un base64 gigante pegado en el chat"): forzamos
    ``encoded=False`` en los kwargs sin importar lo que pida el modelo.
    Con ``encoded=true`` el server oficial de Puppeteer devuelve la
    imagen como TEXTO (data-URI plano) en vez de un bloque
    ``type: "image"``; nuestro parser solo entiende bloques ``image``, y
    si no los encuentra reenvia el texto crudo (el base64 completo) de
    vuelta al modelo, que termina copiandolo en su respuesta final.

    FIX 2 (bug: "el diagrama sale en blanco"): si nos pasaron
    ``navigate_coroutine`` (la tool CRUDA ``puppeteer_navigate``, NUNCA
    expuesta al LLM) y ya hay un bloque ```mermaid``` completo en
    ``response_parts`` (el texto acumulado de la respuesta hasta ahora),
    navegamos el browser a una pagina generada server-side que renderiza
    ese diagrama con mermaid.js ANTES de tomar el screenshot real.
    """
    original_coroutine = tool.coroutine

    async def wrapped(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        # Import lazy (mismo patron que el resto del modulo) para no atar
        # este archivo a langchain_mcp_adapters en tiempo de import.
        from app.core.puppeteer_mcp import _FETCH_TIMEOUT_SECONDS

        # FIX 1: nunca dejamos que el modelo pida el modo "encoded".
        kwargs["encoded"] = False
        if "selector" not in kwargs or not kwargs["selector"]:
            kwargs.pop("selector", None)  # Puppeteer no soporta selector vacío, solo None.

        # FIX 4 (bug: "el diagrama sale en blanco" — causa raiz real):
        # el modelo a veces NUNCA emite el bloque ```mermaid``` como texto
        # visible antes de invocar la tool -- en cambio, cuela el codigo
        # crudo en un kwarg ``content`` que ni siquiera existe en el
        # schema real de ``puppeteer_screenshot`` (propiedad extra, el
        # servidor MCP la ignora). Si eso pasa, ``response_parts`` esta
        # vacio en este punto y el FIX 2 de abajo se salteaba en
        # silencio -- sin excepcion, sin warning -- dejando el screenshot
        # sacado sobre lo que sea que estuviera cargado en el browser.
        # Sacamos el kwarg (no es parte del schema real; no debe
        # reenviarse) y lo usamos como fuente si no hay nada mejor.
        raw_content_kwarg = kwargs.pop("content", None)

        # FIX 2: pre-navegar a la pagina con el mermaid renderizado.
        if navigate_coroutine is not None:
            full_text_so_far = "".join(response_parts) if response_parts is not None else ""
            mermaid_code = extract_mermaid_block(full_text_so_far)
            if mermaid_code is None and isinstance(raw_content_kwarg, str) and raw_content_kwarg.strip():
                # Puede venir ya con fences ```mermaid``` o crudo.
                mermaid_code = extract_mermaid_block(raw_content_kwarg) or raw_content_kwarg.strip()
            if mermaid_code:
                preview_html = _build_mermaid_preview_html(mermaid_code)
                data_url = _mermaid_html_to_data_url(preview_html)
                try:
                    nav_result = await asyncio.wait_for(
                        navigate_coroutine(url=data_url),
                        timeout=_FETCH_TIMEOUT_SECONDS,
                    )
                    # DIAGNOSTIC: algunos servidores MCP devuelven un error
                    # de aplicacion (p.ej. "scheme data: no permitido") como
                    # contenido normal (``isError``/texto) en vez de lanzar
                    # una excepcion Python. Si eso pasa, este ``except`` de
                    # abajo NUNCA se dispara y el fallo queda invisible —
                    # logueamos el resultado crudo para poder distinguir
                    # "navego pero mermaid no termino de renderizar" de
                    # "el navigate fue rechazado en silencio".
                    _LOGGER.info(
                        "Pre-navigate a preview de Mermaid devolvio: %r",
                        nav_result,
                    )
                    # FIX 3 (bug: "el diagrama sale en blanco" — parte 2):
                    # ``navigate`` resuelve en el evento ``load`` del
                    # documento, pero mermaid.js todavia esta parseando y
                    # renderizando el SVG de forma asincrona en ese momento
                    # (fetch del CDN + mermaid.run() interno). Sin este
                    # margen el screenshot se toma antes de que el <pre
                    # class="mermaid"> se reemplace por el SVG renderizado.
                    await asyncio.sleep(_MERMAID_RENDER_DELAY_SECONDS)
                except Exception as e:
                    _LOGGER.warning(
                        "Pre-navigate a preview de Mermaid fallo: %s", e
                    )
                    # No abortamos el turno por esto -- peor caso, el
                    # screenshot sale en blanco como antes del fix, pero
                    # el chat sigue funcionando.

        try:
            content, artifact = await asyncio.wait_for(
                original_coroutine(*args, **kwargs),
                timeout=_FETCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "puppeteer_screenshot no respondió después de %.1fs",
                _FETCH_TIMEOUT_SECONDS,
            )
            return "Puppeteer no devolvió una imagen (timeout).", None
        blocks = content if isinstance(content, list) else []

        image_block = next(
            (b for b in blocks if isinstance(b, dict) and b.get("type") == "image"),
            None,
        )
        if image_block is None:
            text = "\n".join(
                b.get("text", "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            )
            return (text or "Puppeteer no devolvió una imagen."), artifact

        attachment_id = str(uuid.uuid4())
        mime = image_block.get("mime_type") or "image/png"
        ext = "png" if "png" in mime else "jpg"
        filename = f"{attachment_id}.{ext}"
        raw_bytes = base64.b64decode(image_block["base64"])

        uploads_dir = _ensure_uploads_dir()
        storage_path = os.path.join(uploads_dir, filename)
        with open(storage_path, "wb") as f:
            f.write(raw_bytes)

        attachment_sink["pending"] = {
            "id": attachment_id,
            "kind": "screenshot",
            "mime": mime,
            "filename": filename,
            "storage_path": storage_path,
        }

        # Texto corto y plano: esto es lo que ve el modelo, no la imagen.
        return "Diagrama renderizado correctamente.", artifact

    tool.coroutine = wrapped


async def _astream_agent(
    agent: Any,
    message: str,
    callbacks: list[Any],
    *,
    user_id: int | None = None,
    project_id: int | None = None,
    model_name: str | None = None,
    tool_call_tracker: dict[str, int] | None = None,
    attachment_sink: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive ``agent.astream_events`` and yield SSE-ready dicts.

    Token events come from ``on_chat_model_stream`` chunks; tool events come
    from ``on_tool_start`` / ``on_tool_end``. We don't relay
    ``on_chat_model_end`` (the route emits ``done``) nor ``on_chain_*``
    (internal LangChain scaffolding).

    ``user_id`` / ``project_id`` / ``model_name`` flow into the run config
    metadata so Langfuse can label the trace (REQ-5 / SCN-7).

    ``tool_call_tracker`` (optional): a mutable dict whose ``"count"`` key
    is incremented every time a ``tool_start`` event is yielded. ``run_agent``
    uses it to detect the "tools were available but the model never called
    one" case and emit a ``degraded`` event with
    ``reason="tool_calls_missing"`` (PR #76 review fix #2b). Callers that
    don't care can pass ``None``.
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
            if tool_call_tracker is not None:
                tool_call_tracker["count"] = tool_call_tracker.get("count", 0) + 1
            yield {"event": "tool_start", "data": {"tool": name}}
        elif ev_type == "on_tool_end":
            name = raw.get("name") or "tool"
            output = raw.get("data", {}).get("output")
            _, length = _truncate_tool_result(output)
            yield {
                "event": "tool_end",
                "data": {"tool": name, "result_length": length, "status": "ok"},
            }
            if name == "puppeteer_screenshot" and attachment_sink is not None:
                pending = attachment_sink.pop("pending", None)
                if pending is not None:
                    token = (
                        sign_attachment_token(pending["id"], user_id)
                        if user_id is not None
                        else ""
                    )
                    yield {
                        "event": "attachment",
                        "data": {
                            **pending,
                            "url": f"/api/chat/attachments/{pending['id']}?token={token}",
                        },
                    }

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
    """
    docs = _coerce_documents(rag_documents)

    if _has_architect_pattern(docs):
        context7_tools: list[Any] = []
        _LOGGER.info(
            "RAG contains an architect_pattern; skipping Context7 tool fetch "
            "(user_id=%s, project_id=%s)",
            user_id,
            project_id,
        )
    else:
        context7_tools, degraded = await _try_get_context7_tools()
        if degraded is not None:
            yield {"event": "degraded", "data": degraded}

    puppeteer_tools, puppeteer_degraded = await _try_get_puppeteer_tools(
        user_id=user_id,
    )
    if puppeteer_degraded is not None:
        yield {"event": "degraded", "data": puppeteer_degraded}

    # ``response_parts`` se crea ACA (antes de armar el agente) porque el
    # wrapper del screenshot necesita leer el texto acumulado para
    # encontrar el bloque ```mermaid``` ya emitido por el modelo (FIX 2).
    attachment_sink: dict[str, Any] = {}
    response_parts: list[str] = []

    navigate_tool = None
    if puppeteer_tools:
        from app.core.puppeteer_mcp import get_puppeteer_navigate_tool

        navigate_tool = await get_puppeteer_navigate_tool()

    for _t in puppeteer_tools:
        if getattr(_t, "name", None) == "puppeteer_screenshot":
            _wrap_screenshot_tool_for_groq_compat(
                _t,
                attachment_sink,
                navigate_coroutine=(navigate_tool.coroutine if navigate_tool else None),
                response_parts=response_parts,
            )

    system_prompt = _build_system_prompt(docs, puppeteer_available=bool(puppeteer_tools))

    tools: list[Any] = list(context7_tools) + list(puppeteer_tools)

    agent = build_agent(model=model, system_prompt=system_prompt, tools=tools)

    model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
    if not isinstance(model_name, str):
        model_name = None

    tool_call_tracker: dict[str, int] = {"count": 0}

    async for sse_dict in _astream_agent(
        agent,
        message,
        callbacks,
        user_id=user_id,
        project_id=project_id,
        model_name=model_name,
        tool_call_tracker=tool_call_tracker,
        attachment_sink=attachment_sink,
    ):
        if sse_dict.get("event") == "token":
            token_text = sse_dict.get("data")
            if isinstance(token_text, str):
                response_parts.append(token_text)
        yield sse_dict

    if tools and tool_call_tracker["count"] == 0:
        model_label = model_name or "unknown"
        _LOGGER.warning(
            "model=%s user_id=%s project_id=%s produced no tool_calls despite "
            "tools_available=%d (likely weak Tool Calling support); "
            "emitting event: degraded reason=tool_calls_missing",
            model_label,
            user_id,
            project_id,
            len(tools),
        )
        yield {
            "event": "degraded",
            "data": {
                "source": "agent",
                "reason": "tool_calls_missing",
                "fallback": "text_only",
                "message": (
                    f"model '{model_label}' did not emit any tool_calls; "
                    f"tools were advertised but never invoked"
                ),
                "tools_available": len(tools),
            },
        }

    full_response = "".join(response_parts)
    mermaid_code = extract_mermaid_block(full_response)
    if mermaid_code is not None:
        is_valid, error = validate_mermaid(mermaid_code)
        if not is_valid:
            _LOGGER.warning(
                "Mermaid invalido (user_id=%s, project_id=%s): %s",
                user_id,
                project_id,
                error,
            )
        yield {
            "event": "diagram_validated",
            "data": {"valid": is_valid, "error": error},
        }

    yield {"event": "done", "data": None}


__all__ = [
    "ARCHITECT_PERSONA",
    "LIBRARY_HINT",
    "DIAGRAM_HINT",
    "_TOOL_RESULT_MAX_CHARS",
    "build_agent",
    "format_rag_context",
    "run_agent",
]