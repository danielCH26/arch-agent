"""
LangChain agent runtime for Context7 MCP integration.

Exposes ``build_agent``, ``format_rag_context`` and ``run_agent`` — the three
helpers the ``/api/chat`` route uses after slice F11.4b swaps
``model.astream(prompt)`` for ``run_agent(...)``.

Issue: #13 - [F11] Context7 MCP integration.
ADR: docs/adr/010-context7-agent-runtime.md.

SIMPLIFICACIÓN (tras 8h de debugging de tool-calling débil, encoded=true,
placeholders alucinados, imports cruzados, etc.): ``puppeteer_screenshot``
YA NO se le ofrece al LLM como tool. El modelo solo tiene que escribir el
bloque ```mermaid``` en su respuesta (eso lo hace de forma consistente).
El backend SIEMPRE renderiza ese bloque server-side, sin depender de que
el modelo decida invocar nada. Esto elimina de raíz: tool-calling débil,
argumentos inventados (encoded=true), placeholders de imagen alucinados,
y la carrera entre navigate/screenshot.
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

ARCHITECT_PERSONA: str = (
    "Eres un asistente de arquitectura de software. "
    "Responde en español, de forma clara y accionable. "
    "Usa markdown (encabezados, negritas, tablas) libremente, pero NUNCA "
    "envuelvas la respuesta completa dentro de un bloque de codigo (```). "
    "Usa ``` unicamente para fragmentos de codigo real o diagramas ASCII "
    "puntuales, nunca para el mensaje entero."
)

LIBRARY_HINT: str = (
    "Dispones de las herramientas ``resolve-library-id`` y ``query-docs`` "
    "para consultar documentacion de librerias externas (Context7). "
    "Invocalas SOLO cuando el usuario nombre una libreria concreta o "
    "pregunte por la API / uso de un paquete. Para preguntas sobre "
    "patrones de arquitectura cubiertos por el contexto RAG, responde "
    "directamente sin gastar herramientas."
)

# SIMPLIFICADO: ya no menciona ninguna tool de Puppeteer, porque el
# modelo no la tiene disponible. Solo le pedimos el bloque mermaid.
DIAGRAM_HINT: str = (
    "Cuando el usuario pida ver un diagrama, escribe un bloque de codigo "
    "```mermaid ...``` con el diagrama COMPLETO (todos los nodos y "
    "conexiones). Elige el tipo segun lo que pida:\n"
    "- flujo de proceso -> ``flowchart`` o ``graph``\n"
    "- componentes/arquitectura -> ``flowchart`` con subgraphs por "
    "componente\n"
    "- interaccion entre servicios en el tiempo -> ``sequenceDiagram``\n"
    "El sistema se encarga de renderizarlo a imagen automaticamente "
    "despues de que termines de escribir tu respuesta -- vos NUNCA "
    "escribas una etiqueta markdown de imagen (``![...](...)``) ni "
    "ningun data-URI base64; alcanza con el bloque ```mermaid```."
)

_TOOL_RESULT_MAX_CHARS: int = 4000
_RAG_DOCS_CAP: int = 5
_TOOL_RESULT_TRUNCATION_MARKER: str = (
    "... [truncado, ver Langfuse trace para el resultado completo]"
)

# Cuanto esperar despues de navegar a la pagina de preview antes de tomar
# el screenshot, para darle tiempo a mermaid.js a terminar de dibujar.
_MERMAID_RENDER_DELAY_SECONDS: float = 6.0


def _coerce_documents(rag_documents: list[Any] | None) -> list[Any]:
    docs = list(rag_documents or [])[:_RAG_DOCS_CAP]
    return docs


def _has_architect_pattern(rag_documents: list[Any]) -> bool:
    for doc in rag_documents:
        metadata = getattr(doc, "metadata", None)
        if metadata is None and isinstance(doc, dict):
            metadata = doc.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("source_type") == "architect_pattern":
                return True
    return False


def format_rag_context(rag_documents: list[Any]) -> str:
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
    """SIMPLIFICADO: ya no recibe ``puppeteer_available`` -- el DIAGRAM_HINT
    siempre se incluye, porque ya no depende de que exista una tool."""
    hints = f"{LIBRARY_HINT}\n\n{DIAGRAM_HINT}"
    return (
        f"{ARCHITECT_PERSONA}\n\n"
        f"Contexto RAG recuperado:\n{format_rag_context(rag_documents)}\n\n"
        f"{hints}"
    )


def _create_agent(model: Any, tools: list[Any], system_prompt: str) -> Any:
    from langchain.agents import create_agent

    return create_agent(model=model, tools=tools, system_prompt=system_prompt)


def build_agent(
    model: Any,
    system_prompt: str,
    tools: list[Any] | None = None,
) -> Any:
    tool_list = list(tools or [])
    return _create_agent(model=model, tools=tool_list, system_prompt=system_prompt)


def _truncate_tool_result(output: Any) -> tuple[str, int]:
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


def _build_mermaid_preview_html(mermaid_code: str) -> str:
    """Pagina HTML autocontenida que renderiza un bloque Mermaid via
    mermaid.js (CDN).

    DIAGNOSTICO: agrega un <div id="status"> visible en pantalla que
    muestra "Cargando..." / "OK" / "ERROR: <mensaje>". Como el screenshot
    es una foto de lo que se VE, y document.title no aparece en la
    imagen, sin esto un fallo de mermaid.run() era invisible -- la
    pagina quedaba en blanco sin ninguna pista de por que.
    """
    import html as _html

    escaped = _html.escape(mermaid_code)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<script src='https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js'></script>"
        "<style>"
        "html,body{margin:0;padding:0;width:800px;height:600px;background:#fff;"
        "display:flex;align-items:center;justify-content:center;font-family:sans-serif;}"
        "#status{position:absolute;top:8px;left:8px;font-size:14px;color:#a00;white-space:pre-wrap;}"
        ".mermaid svg{max-width:760px;max-height:560px;width:auto;height:auto;}"
        "</style>"
        "</head><body>"
        "<div id='status'>Cargando diagrama...</div>"
        "<pre class='mermaid'>" + escaped + "</pre>"
        "<script>"
        "window.onerror = function(msg) {"
        "  document.getElementById('status').textContent = 'ERROR JS: ' + msg;"
        "};"
        "try {"
        "  mermaid.initialize({startOnLoad:false});"
        "  mermaid.run({querySelector:'.mermaid'})"
        "    .then(function(){"
        "      document.getElementById('status').textContent = '';"
        "      document.title = 'mermaid-rendered';"
        "    })"
        "    .catch(function(e){"
        "      document.getElementById('status').textContent = 'ERROR mermaid.run: ' + (e && e.message ? e.message : e);"
        "      document.title = 'mermaid-error';"
        "    });"
        "} catch (e) {"
        "  document.getElementById('status').textContent = 'ERROR sincrono: ' + e.message;"
        "}"
        "</script>"
        "</body></html>"
    )

def _mermaid_html_to_data_url(html: str) -> str:
    encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f"data:text/html;base64,{encoded}"


async def _render_mermaid_server_side(
    mermaid_code: str,
    *,
    navigate_coroutine: Any | None = None,   # ya no se usa; se deja el parámetro
    screenshot_coroutine: Any = None,        # para no romper la firma de la llamada existente
    fetch_timeout: float = 15.0,
) -> dict[str, Any] | None:
    """Renderiza un bloque mermaid a PNG, abriendo UNA sola sesión MCP
    cruda contra el sidecar de Puppeteer.

    FIX definitivo (bug: "el diagrama sale siempre en blanco"): antes,
    ``navigate`` y ``screenshot`` se invocaban como dos tools de LangChain
    independientes, y ``langchain_mcp_adapters`` abre/cierra su propia
    sesión MCP (y por lo tanto su propio browser) POR CADA llamada --
    ni siquiera activar ``--stateful`` en supergateway lo evita, porque
    el problema está en el cliente Python, no en el gateway. Acá abrimos
    la sesión nosotros mismos con el SDK crudo de ``mcp`` y hacemos
    ``navigate`` + esperar + ``screenshot`` DENTRO de la misma sesión,
    garantizando que comparten el mismo browser/página.
    """
    from app.core.puppeteer_mcp import _resolve_url

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as e:
        _LOGGER.warning(
            "Render server-side: no se pudo importar el SDK crudo de mcp: %s", e
        )
        return None

    preview_html = _build_mermaid_preview_html(mermaid_code)
    data_url = _mermaid_html_to_data_url(preview_html)
    mcp_url = _resolve_url()

    try:
        async with streamablehttp_client(mcp_url) as (read, write, _get_session_id):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=fetch_timeout)

                await asyncio.wait_for(
                    session.call_tool("puppeteer_navigate", {"url": data_url}),
                    timeout=fetch_timeout,
                )

                # Le damos tiempo a mermaid.js (ya embebido inline, sin
                # dependencia de red) a terminar de dibujar el SVG.
                await asyncio.sleep(_MERMAID_RENDER_DELAY_SECONDS)

                result = await asyncio.wait_for(
                    session.call_tool(
                        "puppeteer_screenshot", {"name": "diagram", "encoded": False}
                    ),
                    timeout=fetch_timeout,
                )
    except Exception as e:
        _LOGGER.warning("Render server-side (sesion unica) fallo: %s", e)
        return None

    blocks = getattr(result, "content", None) or []
    image_block = next(
        (b for b in blocks if getattr(b, "type", None) == "image"), None
    )
    if image_block is None:
        text_blocks = [
            getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"
        ]
        _LOGGER.warning(
            "Render server-side: no vino bloque image. Bloques de texto: %s",
            text_blocks,
        )
        return None

    attachment_id = str(uuid.uuid4())
    mime = getattr(image_block, "mimeType", None) or "image/png"
    ext = "png" if "png" in mime else "jpg"
    filename = f"{attachment_id}.{ext}"
    raw_bytes = base64.b64decode(image_block.data)

    uploads_dir = _ensure_uploads_dir()
    storage_path = os.path.join(uploads_dir, filename)
    with open(storage_path, "wb") as f:
        f.write(raw_bytes)

    return {
        "id": attachment_id,
        "kind": "screenshot",
        "mime": mime,
        "filename": filename,
        "storage_path": storage_path,
    }

async def _astream_agent(
    agent: Any,
    message: str,
    callbacks: list[Any],
    *,
    user_id: int | None = None,
    project_id: int | None = None,
    model_name: str | None = None,
    tool_call_tracker: dict[str, int] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive ``agent.astream_events`` and yield SSE-ready dicts.

    SIMPLIFICADO: ya no maneja attachment_sink ni el caso especial de
    ``puppeteer_screenshot`` en ``on_tool_end`` -- esa tool ya no esta
    en la lista que ve el modelo, asi que nunca va a aparecer aca.
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

    SIMPLIFICADO: ``puppeteer_screenshot`` NUNCA se agrega a ``tools``
    (el LLM no la ve). Se usa solo internamente, al final del turno,
    para renderizar el mermaid que el modelo haya escrito.
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

    # Traemos las tools de Puppeteer SOLO para uso interno (nunca se las
    # pasamos a build_agent). Si fallan, seguimos sin diagrama pero sin
    # romper el chat -- el mensaje de texto igual se genera.
    screenshot_coroutine = None
    navigate_coroutine = None
    fetch_timeout = 15.0
    try:
        from app.core.puppeteer_mcp import (
            _FETCH_TIMEOUT_SECONDS,
            _check_rate_limit,
            get_puppeteer_tools_and_navigate,
        )

        fetch_timeout = _FETCH_TIMEOUT_SECONDS
        _check_rate_limit(user_id)
        puppeteer_tools, navigate_tool = await get_puppeteer_tools_and_navigate()
        for _t in puppeteer_tools:
            if getattr(_t, "name", None) == "puppeteer_screenshot":
                screenshot_coroutine = _t.coroutine
        if navigate_tool is not None:
            navigate_coroutine = navigate_tool.coroutine
    except Exception as e:
        _LOGGER.warning(
            "Puppeteer no disponible para user_id=%s; se sigue sin "
            "renderizar diagramas este turno: %s",
            user_id,
            e,
        )

    tools: list[Any] = list(context7_tools)

    system_prompt = _build_system_prompt(docs)
    agent = build_agent(model=model, system_prompt=system_prompt, tools=tools)

    model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
    if not isinstance(model_name, str):
        model_name = None

    tool_call_tracker: dict[str, int] = {"count": 0}
    response_parts: list[str] = []

    async for sse_dict in _astream_agent(
        agent,
        message,
        callbacks,
        user_id=user_id,
        project_id=project_id,
        model_name=model_name,
        tool_call_tracker=tool_call_tracker,
    ):
        if sse_dict.get("event") == "token":
            token_text = sse_dict.get("data")
            if isinstance(token_text, str):
                response_parts.append(token_text)
        yield sse_dict

    if tools and tool_call_tracker["count"] == 0:
        model_label = model_name or "unknown"
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

        # UNICO camino para generar el diagrama: siempre server-side.
        if is_valid and screenshot_coroutine is not None:
            attachment = await _render_mermaid_server_side(
                mermaid_code,
                navigate_coroutine=navigate_coroutine,
                screenshot_coroutine=screenshot_coroutine,
                fetch_timeout=fetch_timeout,
            )
            if attachment is not None:
                token = (
                    sign_attachment_token(attachment["id"], user_id)
                    if user_id is not None
                    else ""
                )
                yield {
                    "event": "attachment",
                    "data": {
                        **attachment,
                        "url": f"/api/chat/attachments/{attachment['id']}?token={token}",
                    },
                }
            else:
                yield {
                    "event": "degraded",
                    "data": {
                        "source": "puppeteer",
                        "reason": "render_failed",
                        "fallback": "text_only",
                        "message": "No se pudo renderizar el diagrama a imagen.",
                    },
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