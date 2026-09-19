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
import re
import uuid
from typing import Any, AsyncIterator

from app.core.attachment_tokens import _ensure_uploads_dir, build_attachment_url
from app.core.mermaid_validator import (
    extract_mermaid_block,
    sanitize_mermaid,
    validate_mermaid,
)

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
    "ningun data-URI base64; alcanza con el bloque ```mermaid```. "
    "Para maximizar que renderice bien: usa IDs simples sin espacios "
    "(por ejemplo API_Gateway), pon textos complejos entre comillas "
    'en los nodos (A["Cliente Web"]), evita caracteres raros dentro de '
    "labels, no uses HTML, y no envuelvas el diagrama en un bloque de "
    "codigo sin el lenguaje mermaid. Si el usuario pide modificar un "
    "diagrama anterior y recibis el Mermaid base, tratá ese bloque como "
    "fuente de verdad: conserva nodos, conexiones, subgraphs, estilos y "
    "capas existentes salvo que el usuario pida quitarlos explicitamente; "
    "aplica solo el cambio pedido y devuelve el diagrama completo. En "
    "ese caso responde unicamente con el bloque ```mermaid``` actualizado, "
    "sin tablas, explicaciones, leyendas ni proximos pasos fuera del bloque."
)

_TOOL_RESULT_MAX_CHARS: int = 4000
_RAG_DOCS_CAP: int = 5
_TOOL_RESULT_TRUNCATION_MARKER: str = (
    "... [truncado, ver Langfuse trace para el resultado completo]"
)

# Hallazgo #9 (revisión feature/hu6-diagrama): antes era una espera fija
# de 6s aplicada siempre, aunque mermaid.run() terminara en <1s. Ahora es
# un TOPE MAXIMO para el polling de document.title (ver
# _wait_for_mermaid_result) -- la mayoria de los diagramas van a tardar
# bastante menos que esto.
_MERMAID_RENDER_MAX_WAIT_SECONDS: float = 6.0
_MERMAID_RENDER_POLL_INTERVAL_SECONDS: float = 0.3

# Hallazgo #4 (revisión feature/hu6-diagrama): mermaid.js se cargaba desde
# `cdn.jsdelivr.net`, lo que no funciona en el sidecar de Puppeteer (sin
# salida a internet). Se vendorizó el bundle (`mermaid.min.js` en la raíz).
#
# Pero embeberlo INLINE en el data URL (~3.3 MB -> ~4.5 MB en base64) tampoco
# funciona en Docker: el data URL viaja como JSON en un POST al sidecar y
# supergateway (`express.json()` sin `limit`) rechaza cuerpos > 100 KB con
# HTTP 413; además Chromium limita las URLs de navegación a ~2 MB. Por eso el
# HTML sigue siendo un data URL chico y solo el <script> apunta al bundle,
# servido por el propio backend (`GET /vendor/mermaid.min.js`, ver server.py)
# dentro de la red de Docker -- sigue sin necesitar internet.
_MERMAID_JS_URL: str = os.environ.get(
    "MERMAID_JS_URL", "http://backend:8000/vendor/mermaid.min.js"
)
_MERMAID_NODE_DEF_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[\s*\"?([^\"\]\n]+?)\"?\s*\]|\[\(\s*([^)]+?)\s*\)\])"
)
_MERMAID_EDGE_ID_PATTERN = re.compile(
    r"(?:^|[\s])([A-Za-z_][A-Za-z0-9_]*)\s*(?=(?:--|==|-.|<--|<==|<-\.))",
    re.MULTILINE,
)
_GROUNDING_IGNORE_NODE_IDS = {
    "TD",
    "TB",
    "BT",
    "LR",
    "RL",
    "subgraph",
    "end",
    "classDef",
    "class",
    "style",
    "linkStyle",
}


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


# Palabras que NO aportan informacion para decidir si un nodo esta respaldado
# (articulos/preposiciones y sustantivos "contenedor" genericos). Se usan solo
# como segundo criterio en `find_ungrounded_mermaid_nodes`.
_GROUNDING_GENERIC_WORDS = frozenset(
    {
        "de", "del", "la", "el", "los", "las", "y", "e", "en", "para", "con",
        "base", "datos", "database", "db", "servicio", "servicios", "service",
        "services",
    }
)


def _normalise_grounding_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _extract_mermaid_node_names(code: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None) -> None:
        if not value:
            return
        cleaned = value.strip().strip('"').strip()
        if not cleaned or cleaned in _GROUNDING_IGNORE_NODE_IDS:
            return
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            names.append(cleaned)

    for match in _MERMAID_NODE_DEF_PATTERN.finditer(code):
        node_id, label, cylinder_label = match.groups()
        _add(label or cylinder_label or node_id.replace("_", " "))

    for match in _MERMAID_EDGE_ID_PATTERN.finditer(code):
        _add(match.group(1).replace("_", " "))

    return names


def _grounding_text_from_docs(rag_documents: list[Any]) -> str:
    chunks: list[str] = []
    for doc in rag_documents:
        metadata = getattr(doc, "metadata", None)
        if metadata is None and isinstance(doc, dict):
            metadata = doc.get("metadata")
        if isinstance(metadata, dict):
            chunks.extend(
                str(metadata.get(key) or "")
                for key in ("pattern_name", "filename", "source_type")
            )

        page = getattr(doc, "page_content", "")
        if not page and isinstance(doc, dict):
            page = doc.get("page_content", "")
        chunks.append(str(page or ""))

    return _normalise_grounding_text("\n".join(chunks))


def find_ungrounded_mermaid_nodes(
    mermaid_code: str,
    rag_documents: list[Any],
) -> list[str]:
    grounding_text = _grounding_text_from_docs(rag_documents)
    if not grounding_text:
        return []

    grounding_words = set(grounding_text.split())

    unknown: list[str] = []
    for node_name in _extract_mermaid_node_names(mermaid_code):
        normalised = _normalise_grounding_text(node_name.replace("_", " "))
        if not normalised:
            continue
        if normalised in grounding_text:
            continue

        # Falso positivo (HU6): la propuesta dice "PostgreSQL" y el modelo
        # rotula el nodo "Base de Datos PostgreSQL". La etiqueta completa no
        # es substring del texto, pero TODAS sus palabras distintivas (las que
        # no son genericas) si aparecen -> el nodo esta respaldado. Un nodo
        # inventado ("Servicio de Blockchain") sigue marcandose porque su
        # palabra distintiva no aparece en el contexto.
        distinctive = [
            w for w in normalised.split() if w not in _GROUNDING_GENERIC_WORDS
        ]
        if distinctive and all(w in grounding_words for w in distinctive):
            continue

        unknown.append(node_name)

    return unknown


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
    mermaid.js (vendorizado, servido por el backend -- ver hallazgo #4), agrandando
    el SVG resultante antes del screenshot para que los textos sean legibles
    en la imagen final.

    El sidecar de Puppeteer no tiene salida a internet, así que un
    `<script src="https://...">` (como se hacía antes) deja `mermaid`
    indefinido y el render falla en silencio tras el timeout completo.
    """
    import html as _html

    escaped = _html.escape(mermaid_code)
    script_url = _html.escape(_MERMAID_JS_URL, quote=True)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<script src='" + script_url + "'></script>"
        "<style>"
        "html,body{margin:0;padding:0;background:#fff;font-family:sans-serif;}"
        "body{display:inline-block;box-sizing:border-box;}"
        "#status{position:absolute;top:8px;left:8px;font-size:14px;color:#a00;"
        "white-space:pre-wrap;}"
        ".mermaid{display:inline-block;padding:24px;background:#fff;}"
        ".mermaid svg{display:block;max-width:none!important;height:auto!important;}"
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
        "      var svg = document.querySelector('.mermaid svg');"
        "      if (svg) {"
        "        var box = svg.getBBox();"
        "        var scale = 3;"
        "        var width = Math.ceil((box.width || svg.clientWidth || 800) * scale);"
        "        var height = Math.ceil((box.height || svg.clientHeight || 600) * scale);"
        "        if (!svg.getAttribute('viewBox')) {"
        "          svg.setAttribute('viewBox', [box.x || 0, box.y || 0, box.width || width, box.height || height].join(' '));"
        "        }"
        "        svg.setAttribute('width', String(width));"
        "        svg.setAttribute('height', String(height));"
        "        svg.style.width = width + 'px';"
        "        svg.style.height = height + 'px';"
        "      }"
        "      document.getElementById('status').textContent = '';"
        "      document.title = 'mermaid-rendered';"
        "    })"
        "    .catch(function(e){"
        "      document.getElementById('status').textContent = 'ERROR mermaid.run: ' + (e && e.message ? e.message : e);"
        "      document.title = 'mermaid-error';"
        "    });"
        "} catch (e) {"
        "  document.getElementById('status').textContent = 'ERROR sincrono: ' + e.message;"
        "  document.title = 'mermaid-error';"
        "}"
        "</script>"
        "</body></html>"
    )

async def _wait_for_mermaid_render(session: Any, *, fetch_timeout: float) -> str:
    """Poll de ``document.title`` hasta que mermaid.js termine (o se agote
    ``_MERMAID_RENDER_MAX_WAIT_SECONDS``).

    Hallazgo #9 (revisión feature/hu6-diagrama): antes se esperaba siempre
    un ``asyncio.sleep`` fijo de 6s antes de mirar el resultado, aunque
    ``mermaid.run()`` terminara en menos de 1s -- cada diagrama sumaba 6s+
    de latencia innecesaria. Ahora se consulta el title cada
    ``_MERMAID_RENDER_POLL_INTERVAL_SECONDS`` y se corta apenas aparece
    ``mermaid-rendered``/``mermaid-error``, con el viejo valor como tope
    máximo por si el render nunca termina.

    Devuelve el último título leído (puede ser el título por defecto de la
    página si nunca llegó a terminar dentro del tope).
    """
    deadline = asyncio.get_event_loop().time() + _MERMAID_RENDER_MAX_WAIT_SECONDS
    last_title = ""
    while True:
        try:
            title_result = await asyncio.wait_for(
                session.call_tool("puppeteer_evaluate", {"script": "document.title"}),
                timeout=fetch_timeout,
            )
            title_blocks = getattr(title_result, "content", None) or []
            last_title = " ".join(
                getattr(b, "text", "") or ""
                for b in title_blocks
                if getattr(b, "type", None) == "text"
            )
        except Exception as e:
            _LOGGER.warning(
                "Render server-side: fallo consultando document.title durante "
                "el polling, sigo con lo que haya: %s", e
            )
            return last_title

        if "mermaid-rendered" in last_title or "mermaid-error" in last_title:
            return last_title
        if asyncio.get_event_loop().time() >= deadline:
            return last_title
        await asyncio.sleep(_MERMAID_RENDER_POLL_INTERVAL_SECONDS)


def _describe_exception(exc: BaseException) -> str:
    """Aplana un ExceptionGroup (p. ej. el ``unhandled errors in a TaskGroup``
    del cliente MCP) para loguear la causa real (``HTTPStatusError 413``,
    ``ConnectError``...) en vez del mensaje generico del grupo."""
    subs = getattr(exc, "exceptions", None)
    if subs:
        return "; ".join(_describe_exception(s) for s in subs)
    return f"{type(exc).__name__}: {exc}"


def _mermaid_html_to_data_url(html: str) -> str:
    encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
    return f"data:text/html;base64,{encoded}"


async def _render_mermaid_server_side(
    mermaid_code: str,
    *,
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

                # Hallazgo #9: en vez de dormir siempre el tope máximo,
                # hacemos polling corto de document.title y cortamos apenas
                # mermaid.js termina (éxito o error).
                #
                # Bug fix (HU6, "se petó" con diagramas mas complejos): el
                # validador de mermaid_validator.py es un heuristico, no un
                # parser real -- puede dejar pasar sintaxis que Mermoid
                # SI rechaza en el navegador. Antes de este fix, tomabamos
                # el screenshot sin mirar si mermaid.run() habia tenido
                # exito o no, asi que un error de Mermaid terminaba
                # sirviendose como si fuera el diagrama (captura del
                # mensaje de error en rojo). _build_mermaid_preview_html
                # ya setea document.title a 'mermaid-rendered' o
                # 'mermaid-error' segun el resultado -- lo chequeamos aca.
                # Fail-open: si este chequeo extra falla por lo que sea,
                # seguimos con el flujo viejo (mejor un screenshot
                # ocasionalmente malo que romper el caso feliz).
                try:
                    title_text = await _wait_for_mermaid_render(
                        session, fetch_timeout=fetch_timeout
                    )
                    if "mermaid-error" in title_text:
                        # Antes solo mirabamos el title ("mermaid-error"), que
                        # no dice NADA sobre la causa real. El HTML de preview
                        # ya guarda el mensaje real de mermaid.run() en
                        # #status (ver _build_mermaid_preview_html) -- lo
                        # leemos aca para poder debuggear sin adivinar.
                        status_text = "(no se pudo leer #status)"
                        try:
                            status_result = await asyncio.wait_for(
                                session.call_tool(
                                    "puppeteer_evaluate",
                                    {
                                        "script": (
                                            "document.getElementById('status')"
                                            "?.textContent || ''"
                                        )
                                    },
                                ),
                                timeout=fetch_timeout,
                            )
                            status_blocks = getattr(status_result, "content", None) or []
                            status_text = " ".join(
                                getattr(b, "text", "") or ""
                                for b in status_blocks
                                if getattr(b, "type", None) == "text"
                            ) or "(vacio)"
                        except Exception as status_exc:
                            status_text = f"(fallo leyendo #status: {status_exc})"

                        _LOGGER.warning(
                            "Render server-side: mermaid.run() fallo en el "
                            "navegador. Error real: %s | Mermaid completo:\n%s",
                            status_text,
                            mermaid_code,
                        )
                        return None
                except Exception as e:
                    _LOGGER.warning(
                        "Render server-side: no se pudo verificar el title "
                        "post-render, sigo igual: %s", e
                    )

                result = await asyncio.wait_for(
                    session.call_tool(
                        "puppeteer_screenshot",
                        {"name": "diagram", "encoded": False, "selector": ".mermaid svg"},
                    ),
                    timeout=fetch_timeout,
                )
    except Exception as e:
        _LOGGER.warning(
            "Render server-side (sesion unica) fallo: %s", _describe_exception(e)
        )
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
        elif ev_type == "on_tool_error":
            name = raw.get("name") or "tool"
            error = raw.get("data", {}).get("error")
            # Hallazgo #11 (revisión feature/hu6-diagrama): antes se mandaba
            # `str(error)` crudo en el evento SSE. `sse.py::_emit_tool_end`
            # deliberadamente NO hace esto (solo usa el error para calcular
            # `result_length`, nunca lo pone en el payload) porque un error
            # de tool puede exponer hosts internos, paths del filesystem,
            # o detalle de infraestructura. Acá loggeamos el detalle
            # completo solo server-side y mandamos un mensaje genérico.
            _LOGGER.warning("Tool '%s' failed: %s", name, error)
            yield {
                "event": "tool_end",
                "data": {
                    "tool": name,
                    "result_length": 0,
                    "status": "error",
                    "error": "Error ejecutando la herramienta.",
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

    # Hallazgo #2 (revisión feature/hu6-diagrama): antes se llamaba
    # `_check_rate_limit(user_id)` ACA, al principio de TODOS los turnos --
    # no solo los que terminan generando un diagrama. Eso gastaba una de
    # las 5 llamadas/minuto en cualquier mensaje de chat normal, y cuando
    # se agotaba, el bloque de degraded (mas abajo, dentro de
    # `if is_valid and puppeteer_available`) ni se ejecutaba porque
    # `is_valid` todavia no existe en este punto del turno -- resultado:
    # bloque mermaid valido, sin imagen, sin `event: degraded`, sin nota.
    #
    # Ahora solo se importa `_FETCH_TIMEOUT_SECONDS` aca (no gasta rate
    # limit); el chequeo de rate limit en si se mueve mas abajo, justo
    # antes de `_render_mermaid_server_side`, que es el unico lugar que
    # realmente necesita a Puppeteer.
    fetch_timeout = 15.0
    try:
        from app.core.puppeteer_mcp import _FETCH_TIMEOUT_SECONDS

        fetch_timeout = _FETCH_TIMEOUT_SECONDS
    except Exception as e:
        _LOGGER.warning(
            "No se pudo leer _FETCH_TIMEOUT_SECONDS de puppeteer_mcp, "
            "uso el default de %.1fs: %s", fetch_timeout, e,
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
        mermaid_code = sanitize_mermaid(mermaid_code)
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
        if is_valid:
            ungrounded_nodes = find_ungrounded_mermaid_nodes(mermaid_code, docs)
            if ungrounded_nodes:
                yield {
                    "event": "degraded",
                    "data": {
                        "source": "agent",
                        "reason": "diagram_grounding_warning",
                        "fallback": "render_with_warning",
                        "message": (
                            "El diagrama contiene nodos que no aparecen "
                            "claramente en el contexto RAG/propuesta aprobada."
                        ),
                        "nodes": ungrounded_nodes[:20],
                    },
                }

        # UNICO camino para generar el diagrama: siempre server-side.
        # `_render_mermaid_server_side` abre y gestiona su propia sesion
        # MCP (navigate + screenshot en la misma sesion) -- ya no se
        # ofrecen tools de puppeteer al LLM (ver hallazgo #12, revisión
        # feature/hu6-diagrama).
        if is_valid:
            # Hallazgo #2: el rate limit se chequea RECIEN ACA, que es el
            # unico lugar del turno que realmente va a usar Puppeteer. Si
            # se agoto, se emite `degraded` con el `reason` real en vez de
            # omitir el diagrama en silencio.
            try:
                from app.core.puppeteer_mcp import _check_rate_limit

                _check_rate_limit(user_id)
                puppeteer_available = True
            except Exception as e:
                puppeteer_available = False
                reason = getattr(e, "reason", "puppeteer_unavailable") or "puppeteer_unavailable"
                _LOGGER.warning(
                    "Puppeteer no disponible para user_id=%s; se sigue sin "
                    "renderizar el diagrama de este turno: %s",
                    user_id,
                    e,
                )
                yield {
                    "event": "degraded",
                    "data": {
                        "source": "puppeteer",
                        "reason": reason,
                        "fallback": "text_only",
                        "message": str(e) or "Puppeteer no disponible en este momento.",
                    },
                }

            if puppeteer_available:
                attachment = await _render_mermaid_server_side(
                    mermaid_code,
                    fetch_timeout=fetch_timeout,
                )
                if attachment is not None:
                    url = (
                        build_attachment_url(attachment["id"], user_id)
                        if user_id is not None
                        else ""
                    )
                    yield {
                        "event": "attachment",
                        "data": {
                            **attachment,
                            "url": url,
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
    "find_ungrounded_mermaid_nodes",
    "format_rag_context",
    "run_agent",
]