"""
Diagrama de despliegue: del plan de mapeo a una imagen PNG.

Se arma una página HTML autocontenida (los íconos van embebidos como data
URI) y se renderiza con el MISMO sidecar de Puppeteer que ya dibuja los
diagramas Mermaid de HU6.

Por qué HTML y no la librería `diagrams` de Python: esa librería necesita el
binario de Graphviz, que no está en `backend/Dockerfile`; meterlo obliga a
reconstruir la imagen y suma dependencias del sistema. El camino
HTML -> data URL -> `puppeteer_navigate` + `puppeteer_screenshot` ya existe,
ya funciona en producción y devuelve un adjunto con la misma forma, así que
el diagrama de despliegue hereda gratis el historial de versiones y el
flujo de aprobación.

La sesión MCP se abre aquí y no se reutiliza la de `agent.py` a propósito:
son unas líneas duplicadas a cambio de que un fallo en esta función nueva
no pueda romper el diagrama de arquitectura, que es el que ya está
entregado y probado.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from app.core.attachment_tokens import _ensure_uploads_dir
from app.core.cloud_catalog import CloudService, icon_data_uri
from app.core.deployment_mapper import DeploymentPlan

_LOGGER = logging.getLogger(__name__)

# Título que pone la página cuando terminó de dibujar; se consulta por
# polling igual que `mermaid-rendered`, para no tomar la captura antes de
# que estén trazadas las flechas.
_READY_TITLE = "deployment-rendered"
_ERROR_TITLE = "deployment-error"
_RENDER_POLL_INTERVAL_SECONDS = 0.25
_RENDER_TIMEOUT_SECONDS = 20.0

# Selector del nodo que se captura. Se recorta al lienzo para que la imagen
# no traiga el blanco sobrante de la ventana del navegador.
_CAPTURE_SELECTOR = "#canvas"


def _service_card(service: CloudService, components: list[str], *, is_bridge: bool) -> str:
    """Tarjeta de un servicio: logo oficial, nombre y qué componente aloja."""
    hosted = (
        "".join(f"<li>{html.escape(c)}</li>" for c in components)
        if components
        else "<li class='bridge-note'>Lo agrega el proveedor para conectar las piezas</li>"
    )
    return (
        f"<div class='card{' bridge' if is_bridge else ''}' "
        f"id='svc-{html.escape(service.id)}' style='--card-bg:{service.color}'>"
        f"<img class='logo' alt='' src='{icon_data_uri(service)}'>"
        f"<div class='card-text'>"
        f"<span class='svc-name'>{html.escape(service.name)}</span>"
        f"<span class='svc-cat'>{html.escape(service.category_label)}</span>"
        f"<ul class='hosts'>{hosted}</ul>"
        f"</div></div>"
    )


def build_deployment_html(plan: DeploymentPlan, *, project_name: str = "") -> str:
    """Página autocontenida con el diagrama de despliegue.

    El layout lo hace CSS (una columna por `tier`, de la entrada a la
    operación) y las flechas las traza un script al final, midiendo dónde
    quedó cada tarjeta. Calcularlas en Python obligaría a reimplementar el
    layout del navegador; así se dibujan sobre las posiciones reales.
    """
    provider = plan.provider
    bridge_ids = {b.id for b in plan.bridges}

    # Columnas: solo los tiers que tienen algo, en el orden del catálogo.
    services_by_tier: dict[str, list[CloudService]] = {}
    for service in plan.services:
        services_by_tier.setdefault(service.tier, []).append(service)

    # Columna de terceros: no son servicios de la nube, así que no tienen
    # logo ni categoría. Se dibujan con borde punteado para que se lea de un
    # vistazo que esa parte no la despliegas tú.
    external_column = ""
    if plan.externals:
        cards = "".join(
            f"<div class='card external' id='svc-{html.escape(ext.id)}'>"
            # SVG y no un carácter: la fuente del contenedor de Puppeteer no
            # tiene flechas Unicode y salía el cuadrito de "glifo ausente".
            f"<div class='ext-glyph' aria-hidden='true'>"
            f"<svg viewBox='0 0 24 24' width='18' height='18' fill='none' "
            f"stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            f"stroke-linejoin='round'>"
            f"<path d='M10 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4'/>"
            f"<path d='M14 4h6v6'/><path d='M20 4l-8 8'/>"
            f"</svg></div>"
            f"<div class='card-text'>"
            f"<span class='svc-name'>{html.escape(ext.name)}</span>"
            f"<span class='svc-cat'>Servicio de un tercero</span>"
            f"<ul class='hosts'><li class='bridge-note'>Se consume por API; "
            f"no se despliega en {html.escape(provider.short_name)}</li></ul>"
            f"</div></div>"
            for ext in plan.externals
        )
        external_column = (
            f"<div class='col'><div class='col-head'>Externos</div>"
            f"<div class='col-body'>{cards}</div></div>"
        )

    columns = []
    for tier in provider.tiers:
        services = services_by_tier.get(tier.id)
        if not services:
            continue
        cards = "".join(
            _service_card(
                service,
                plan.components_for(service.id),
                is_bridge=service.id in bridge_ids,
            )
            for service in services
        )
        columns.append(
            f"<div class='col'><div class='col-head'>{html.escape(tier.label)}</div>"
            f"<div class='col-body'>{cards}</div></div>"
        )

    edges_json = json.dumps([{"from": a, "to": b} for a, b in plan.connections])

    subtitle = html.escape(project_name) if project_name else "Arquitectura aprobada"
    unmapped_note = ""
    if plan.unmapped:
        items = ", ".join(html.escape(u) for u in plan.unmapped)
        unmapped_note = (
            f"<div class='warn'>Sin equivalente directo en {html.escape(provider.short_name)}: "
            f"{items}</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><title>deployment-loading</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #fff;
    font-family: "Segoe UI", Helvetica, Arial, sans-serif; }}
  body {{ display: inline-block; }}
  #canvas {{ position: relative; display: inline-block; padding: 28px 32px 24px;
    background: #fff; }}
  header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }}
  .brand {{ width: 10px; height: 34px; border-radius: 3px;
    background: {provider.color}; }}
  h1 {{ margin: 0; font-size: 19px; color: #0f172a; }}
  .sub {{ margin: 2px 0 0; font-size: 12px; color: #64748b; }}
  /* El SVG va DEBAJO de las tarjetas: las flechas no deben taparlas. */
  svg#wires {{ position: absolute; inset: 0; width: 100%; height: 100%;
    pointer-events: none; z-index: 0; }}
  .cols {{ position: relative; z-index: 1; display: flex; align-items: flex-start;
    gap: 58px; }}
  .col {{ display: flex; flex-direction: column; gap: 10px; }}
  .col-head {{ font-size: 10px; font-weight: 700; letter-spacing: .09em;
    text-transform: uppercase; color: #94a3b8; padding-left: 2px; }}
  .col-body {{ display: flex; flex-direction: column; gap: 14px; }}
  .card {{ display: flex; align-items: flex-start; gap: 10px; width: 216px;
    padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 10px;
    background: var(--card-bg); box-shadow: 0 1px 2px rgba(15,23,42,.06); }}
  .card.bridge {{ border-style: dashed; border-color: #cbd5e1; }}
  .card.external {{ border-style: dashed; border-color: #a5b4fc;
    background: #fafaff; }}
  .ext-glyph {{ width: 34px; height: 34px; flex: 0 0 34px; border-radius: 8px;
    background: #eef2ff; color: #4f46e5; font-size: 18px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; }}
  .logo {{ width: 34px; height: 34px; object-fit: contain; flex: 0 0 34px; }}
  .card-text {{ display: flex; flex-direction: column; min-width: 0; }}
  .svc-name {{ font-size: 12.5px; font-weight: 700; color: #0f172a;
    line-height: 1.25; }}
  .svc-cat {{ font-size: 10px; color: #64748b; margin-top: 1px; }}
  .hosts {{ margin: 6px 0 0; padding-left: 14px; }}
  .hosts li {{ font-size: 10.5px; color: #334155; line-height: 1.35; }}
  .hosts li.bridge-note {{ color: #94a3b8; font-style: italic; }}
  .warn {{ margin-top: 18px; font-size: 11px; color: #92400e;
    background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
    padding: 7px 10px; max-width: 760px; }}
  footer {{ margin-top: 16px; font-size: 10px; color: #94a3b8; }}
</style></head>
<body>
<div id="canvas">
  <header>
    <div class="brand"></div>
    <div>
      <h1>Despliegue en {html.escape(provider.name)}</h1>
      <p class="sub">{subtitle}</p>
    </div>
  </header>
  <svg id="wires"><defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"></path>
    </marker>
  </defs></svg>
  <div class="cols">{''.join(columns)}{external_column}</div>
  {unmapped_note}
  <footer>Generado por ArchAgent · los logos pertenecen a {html.escape(provider.name)}</footer>
</div>
<script>
(function () {{
  var EDGES = {edges_json};
  try {{
    var canvas = document.getElementById('canvas');
    var svg = document.getElementById('wires');
    var base = canvas.getBoundingClientRect();
    var SVG_NS = 'http://www.w3.org/2000/svg';

    EDGES.forEach(function (edge) {{
      var a = document.getElementById('svc-' + edge.from);
      var b = document.getElementById('svc-' + edge.to);
      if (!a || !b) {{ return; }}
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      var x1, y1, x2, y2;
      // Si están en columnas distintas, la flecha sale por el costado; si
      // comparten columna, por arriba/abajo. Así no cruza las tarjetas.
      if (Math.abs(rb.left - ra.left) > 8) {{
        var leftToRight = rb.left > ra.left;
        x1 = (leftToRight ? ra.right : ra.left) - base.left;
        x2 = (leftToRight ? rb.left : rb.right) - base.left;
        y1 = ra.top + ra.height / 2 - base.top;
        y2 = rb.top + rb.height / 2 - base.top;
      }} else {{
        var downward = rb.top > ra.top;
        x1 = ra.left + ra.width / 2 - base.left;
        x2 = rb.left + rb.width / 2 - base.left;
        y1 = (downward ? ra.bottom : ra.top) - base.top;
        y2 = (downward ? rb.top : rb.bottom) - base.top;
      }}
      var path = document.createElementNS(SVG_NS, 'path');
      var mx = (x1 + x2) / 2;
      path.setAttribute('d',
        'M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 +
        ' ' + x2 + ',' + y2);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', '#94a3b8');
      path.setAttribute('stroke-width', '1.6');
      path.setAttribute('marker-end', 'url(#arrow)');
      svg.appendChild(path);
    }});
    // El SVG se posiciona con inset:0 sobre #canvas, pero necesita un
    // viewBox con las medidas reales para que las coordenadas calculadas
    // arriba (en píxeles de la página) coincidan con las del dibujo.
    svg.setAttribute('viewBox', '0 0 ' + canvas.scrollWidth + ' ' + canvas.scrollHeight);
    svg.setAttribute('width', canvas.scrollWidth);
    svg.setAttribute('height', canvas.scrollHeight);
    document.title = '{_READY_TITLE}';
  }} catch (err) {{
    // Fail-open: mejor el diagrama sin flechas que ninguna imagen.
    document.title = '{_ERROR_TITLE}';
  }}
}})();
</script>
</body></html>"""


def _html_to_data_url(page_html: str) -> str:
    encoded = base64.b64encode(page_html.encode("utf-8")).decode("ascii")
    return f"data:text/html;base64,{encoded}"


# --------------------------------------------------------------------------
# Entrega de la página al navegador
# --------------------------------------------------------------------------
#
# La página NO se manda como `data:` URL. Lleva los logos embebidos, así que
# pesa más de 100 KB, y el transporte del sidecar de Puppeteer rechaza una
# petición de ese tamaño (el mismo 413 que ya documenta `agent.py` para este
# camino). En vez de eso se guarda aquí un momento y el navegador la pide por
# HTTP al backend -- exactamente como ya hace con `mermaid.min.js`, que se
# sirve desde `http://backend:8000/vendor/`.
#
# El token es un UUID y la página vive dos minutos: lo justo para que el
# navegador la cargue. No lleva datos sensibles (es el mismo diagrama que el
# usuario está viendo), pero igual se caduca en vez de dejarla en memoria.

_PENDING_PAGES: dict[str, tuple[float, str]] = {}
_PAGE_TTL_SECONDS = 120.0

# El backend visto DESDE el contenedor de Puppeteer. Constante por defecto,
# igual que `MERMAID_JS_URL`, y configurable si el despliegue cambia de
# nombres de servicio.
RENDER_BASE_URL: str = os.getenv("DEPLOYMENT_RENDER_BASE_URL", "http://backend:8000")


def _prune_pages(now: float) -> None:
    for token in [t for t, (born, _h) in _PENDING_PAGES.items() if now - born > _PAGE_TTL_SECONDS]:
        _PENDING_PAGES.pop(token, None)


def stash_page(page_html: str) -> str:
    """Guarda la página y devuelve el token con el que pedirla."""
    now = time.monotonic()
    _prune_pages(now)
    token = uuid.uuid4().hex
    _PENDING_PAGES[token] = (now, page_html)
    return token


def take_page(token: str) -> Optional[str]:
    """La página de ese token, o ``None`` si no existe o ya caducó."""
    now = time.monotonic()
    _prune_pages(now)
    entry = _PENDING_PAGES.get(token)
    return entry[1] if entry else None


def _describe_exception(exc: BaseException) -> str:
    """Aplana un ExceptionGroup para que el log diga la causa REAL.

    Sin esto, el cliente MCP registra "unhandled errors in a TaskGroup
    (1 sub-exception)", que no dice nada. Mismo helper que `agent.py`;
    se repite aquí para no importar ese módulo (que arrastra el agente
    entero) desde el camino del despliegue.
    """
    subs = getattr(exc, "exceptions", None)
    if subs:
        return "; ".join(_describe_exception(s) for s in subs)
    return f"{type(exc).__name__}: {exc}"


async def _wait_until_drawn(session: Any, *, deadline: float, fetch_timeout: float) -> str:
    """Espera a que el script termine, mirando `document.title`."""
    last = ""
    while True:
        try:
            result = await asyncio.wait_for(
                session.call_tool("puppeteer_evaluate", {"script": "document.title"}),
                timeout=fetch_timeout,
            )
            blocks = getattr(result, "content", None) or []
            last = " ".join(
                getattr(b, "text", "") or ""
                for b in blocks
                if getattr(b, "type", None) == "text"
            )
        except Exception as exc:
            _LOGGER.warning(
                "Despliegue: no se pudo leer document.title, sigo igual: %s", exc
            )
            return last
        if _READY_TITLE in last or _ERROR_TITLE in last:
            return last
        if asyncio.get_event_loop().time() >= deadline:
            return last
        await asyncio.sleep(_RENDER_POLL_INTERVAL_SECONDS)


async def render_deployment_diagram(
    plan: DeploymentPlan,
    *,
    project_name: str = "",
    fetch_timeout: float = 15.0,
) -> Optional[dict[str, Any]]:
    """Renderiza el plan a PNG y devuelve el adjunto, o ``None`` si falla.

    El contrato de fallo es el mismo que el del diagrama Mermaid: se
    registra y se devuelve ``None``, para que quien llama decida qué
    mostrar. Nunca lanza.
    """
    from app.core.puppeteer_mcp import _max_render_bytes, _resolve_url

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:
        _LOGGER.warning("Despliegue: no se pudo importar el SDK de mcp: %s", exc)
        return None

    page_html = build_deployment_html(plan, project_name=project_name)
    # Se publica y se navega a una URL corta en vez de mandar la página
    # entera en la petición (ver el comentario de `stash_page`).
    token = stash_page(page_html)
    page_url = f"{RENDER_BASE_URL.rstrip('/')}/api/deployments/render/{token}"

    try:
        async with streamablehttp_client(_resolve_url()) as (read, write, _sid):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=fetch_timeout)
                await asyncio.wait_for(
                    session.call_tool("puppeteer_navigate", {"url": page_url}),
                    timeout=fetch_timeout,
                )
                deadline = asyncio.get_event_loop().time() + _RENDER_TIMEOUT_SECONDS
                await _wait_until_drawn(
                    session, deadline=deadline, fetch_timeout=fetch_timeout
                )
                result = await asyncio.wait_for(
                    session.call_tool(
                        "puppeteer_screenshot",
                        {
                            "name": "deployment",
                            "encoded": False,
                            "selector": _CAPTURE_SELECTOR,
                        },
                    ),
                    timeout=fetch_timeout,
                )
    except Exception as exc:
        _LOGGER.warning(
            "Despliegue: el render falló navegando a %s: %s",
            page_url,
            _describe_exception(exc),
        )
        return None
    finally:
        _PENDING_PAGES.pop(token, None)

    blocks = getattr(result, "content", None) or []
    image_block = next((b for b in blocks if getattr(b, "type", None) == "image"), None)
    if image_block is None:
        _LOGGER.warning("Despliegue: la captura no trajo bloque de imagen.")
        return None

    # Mismo tope de bytes que el diagrama de arquitectura: una captura
    # enorme no puede llegar a la fila de adjuntos ni al disco.
    max_bytes = _max_render_bytes()
    encoded_png = getattr(image_block, "data", None) or ""
    if len(encoded_png) > ((max_bytes + 2) // 3) * 4:
        _LOGGER.warning(
            "Despliegue: captura de %d chars codificados sobre el tope de %d bytes.",
            len(encoded_png),
            max_bytes,
        )
        return None
    raw_bytes = base64.b64decode(encoded_png)
    if len(raw_bytes) > max_bytes:
        _LOGGER.warning(
            "Despliegue: captura de %d bytes sobre el tope de %d.",
            len(raw_bytes),
            max_bytes,
        )
        return None

    attachment_id = str(uuid.uuid4())
    mime = getattr(image_block, "mimeType", None) or "image/png"
    ext = "png" if "png" in mime else "jpg"
    filename = f"{attachment_id}.{ext}"
    storage_path = os.path.join(_ensure_uploads_dir(), filename)
    with open(storage_path, "wb") as handle:
        handle.write(raw_bytes)

    return {
        "id": attachment_id,
        # Tipo propio: el historial de diagramas de arquitectura filtra por
        # "screenshot", así que un diagrama de despliegue no se cuela ahí.
        "kind": "deployment",
        "mime": mime,
        "filename": filename,
        "storage_path": storage_path,
        "provider": plan.provider.id,
    }
