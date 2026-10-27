"""Identidad visual del ADR ("ArchAgent Blueprint").

Una sola paleta de azules para todo lo que ve el cliente del documento: el
PDF (``frontend/src/components/adrTheme.ts`` tiene los mismos valores; un test
comprueba que no se separen), los diagramas que se dibujan con Puppeteer y el
bloque Mermaid del ``.md`` (GitHub y GitLab lo dibujan con estos colores).

Reglas de uso en ``.atl/skills/adr-design/SKILL.md``.
"""

from __future__ import annotations

import json

# Azules de la marca, del más oscuro al más claro, más neutros y apoyo.
# Cambiar un valor aquí obliga a cambiarlo en adrTheme.ts (test de paridad).
ADR_PALETTE: dict[str, str] = {
    # Azules
    "navy": "#0B1F3A",  # portada, encabezado de tablas, títulos de capítulo
    "primary": "#1D4E89",  # títulos, enlaces, bordes de acento
    "secondary": "#2F74D0",  # subtítulos, viñetas, bordes de nodos
    "accent": "#38A3D9",  # detalles (filete de portada, numeración)
    "sky": "#D6E6F8",  # bordes suaves, nodos secundarios
    "tint": "#EEF4FC",  # fondos de recuadros y nodos
    # Neutros
    "ink": "#1B2533",  # texto
    "muted": "#5B6B80",  # texto secundario, pies de figura
    "line": "#D9E2EC",  # filetes y bordes de tabla
    "paper": "#F7F9FC",  # filas alternas, bloques de código
    # Apoyo (solo para estados, nunca decorativos)
    "success": "#1E7B4F",
    "success_bg": "#E3F4EA",
    "warning": "#9A5B00",
    "warning_bg": "#FFF4DD",
    "danger": "#B42318",
    "danger_bg": "#FDECEA",
}

ADR_FONTS = {
    "heading": "'Plus Jakarta Sans', 'Segoe UI', Helvetica, Arial, sans-serif",
    "body": "'Inter', 'Segoe UI', Helvetica, Arial, sans-serif",
    "mono": "'JetBrains Mono', Consolas, 'Courier New', monospace",
}


def mermaid_theme_config() -> dict:
    """Configuración de Mermaid (tema ``base``) con la paleta del ADR."""
    p = ADR_PALETTE
    return {
        "theme": "base",
        "themeVariables": {
            # Comillas dobles, como el valor por defecto de Mermaid.
            "fontFamily": ADR_FONTS["body"].replace("'", '"'),
            "fontSize": "15px",
            "background": "#FFFFFF",
            "primaryColor": p["tint"],
            "primaryBorderColor": p["secondary"],
            "primaryTextColor": p["navy"],
            "secondaryColor": p["sky"],
            "secondaryBorderColor": p["primary"],
            "secondaryTextColor": p["navy"],
            "tertiaryColor": p["paper"],
            "tertiaryBorderColor": p["line"],
            "tertiaryTextColor": p["ink"],
            "lineColor": p["primary"],
            "textColor": p["ink"],
            "clusterBkg": p["paper"],
            "clusterBorder": p["sky"],
            "titleColor": p["navy"],
            "edgeLabelBackground": "#FFFFFF",
            "nodeTextColor": p["navy"],
            # Diagramas de secuencia
            "actorBkg": p["tint"],
            "actorBorder": p["secondary"],
            "actorTextColor": p["navy"],
            "signalColor": p["primary"],
            "signalTextColor": p["ink"],
            "noteBkgColor": p["warning_bg"],
            "noteBorderColor": p["warning"],
        },
    }


_INIT_DIRECTIVE_PREFIX = "%%{init"


def themed_mermaid(code: str) -> str:
    """El código Mermaid con la directiva ``init`` del tema del ADR al inicio.

    Si el diagrama ya trae su propia directiva, se respeta tal cual.
    """
    body = (code or "").strip()
    if not body or body.lstrip().startswith(_INIT_DIRECTIVE_PREFIX):
        return body
    directive = json.dumps(mermaid_theme_config(), ensure_ascii=False, separators=(",", ":"))
    return f"%%{{init: {directive}}}%%\n{body}"
