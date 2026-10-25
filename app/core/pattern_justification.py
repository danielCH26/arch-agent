"""HU8 -- justificación de propuestas basada en patrones reconocidos.

Lógica pura (sin DB ni LLM). Definición de "la propuesta cita patrones":

    La propuesta nombra un patrón principal (línea ``Patrón principal: X`` en
    ``## Patrones``), ese patrón es la fuente ``primary`` recuperada del RAG y
    la sección ``## Justificación del patrón principal`` tiene contenido.

No se exige citar cada decisión (React, PostgreSQL, Jest...): el catálogo solo
tiene patrones de arquitectura y forzar esas citas hace que el LLM invente
fuentes. Con esa definición se mide el KR "≥80% de propuestas citan patrones".

1. ``source_for`` describe de dónde sale cada cita para que el usuario la
   verifique (``GET /api/patterns/{pattern_id}``).
2. ``analyze_justification`` comprueba la definición de arriba sobre el
   markdown guardado y sus citas. No modifica sus argumentos.
3. ``summarize_citation_rate`` agrega varios análisis para el KR.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# KR de HU8: al menos el 80% de las propuestas debe citar patrones.
CITATION_TARGET_RATE = 0.8

CURATED_SOURCE_LABEL = "Catálogo curado de patrones (arch-agent)"

# "- Patrón principal: **Monolito modular** [1]" -> "Monolito modular".
# Se busca sobre texto normalizado (sin acentos, en minúsculas).
_PRIMARY_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])?[ \t]*[*_]*patron principal[*_]*[ \t]*:[ \t]*(.+?)[ \t]*$",
    re.MULTILINE,
)
_HEADING_RE = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.*)$", re.MULTILINE)
# Mismo criterio que el encabezado "Patrones" de proposal_generator._REQUIRED_HEADINGS.
_PATTERNS_HEADING_RE = re.compile(r"^[*_`\d.)\s]*patr(?:on|ones)\b")
_CODE_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.MULTILINE | re.DOTALL)
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
_TRAILING_REFS_RE = re.compile(r"(?:\s*\[\d+\])+\s*$")


def _normalize(text: str | None) -> str:
    """Minúsculas, sin acentos y con espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _clean_pattern_name(raw: str) -> str:
    """Quita negritas, referencias ``[n]`` y puntuación final del nombre declarado."""
    name = _TRAILING_REFS_RE.sub("", raw)
    name = name.strip().strip("*_`").strip()
    return name.rstrip(".;,").strip()


def source_for(metadata: dict) -> dict:
    """Describe de dónde sale el texto citado (catálogo curado o documento subido)."""
    filename = metadata.get("source_filename")
    if filename:
        return {
            "type": "source_upload",
            "label": f"Documento fuente: {filename}",
            "filename": filename,
        }
    return {"type": "curated_catalog", "label": CURATED_SOURCE_LABEL, "filename": None}


def _primary_citation(citations: Iterable[dict]) -> dict | None:
    for citation in citations:
        if citation.get("source_role") == "primary":
            return citation
    return None


def _patterns_section(normalized_markdown: str) -> str:
    """Texto de ``## Patrones`` hasta el siguiente encabezado del mismo nivel o superior.

    Los bloques de código se descartan antes, para no leer un ``#`` o un
    ``Patrón principal:`` que esté dentro de uno.
    """
    text = _CODE_FENCE_RE.sub("", normalized_markdown)
    headings = list(_HEADING_RE.finditer(text))
    for position, heading in enumerate(headings):
        if not _PATTERNS_HEADING_RE.match(heading.group(2)):
            continue
        level = len(heading.group(1))
        end = len(text)
        for following in headings[position + 1:]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        return text[heading.end():end]
    return ""


def _declared_primary(normalized_markdown: str) -> str | None:
    match = _PRIMARY_LINE_RE.search(_patterns_section(normalized_markdown))
    if match is None:
        return None
    name = _clean_pattern_name(match.group(1))
    return name or None


def _names_match(declared: str, pattern_name: str) -> bool:
    """El nombre declarado es el patrón o uno de sus alias, con igualdad exacta.

    Reutiliza los alias de ``proposal_generator`` ("Arquitectura hexagonal
    (Puertos y Adaptadores)" -> "hexagonal", "puertos y adaptadores"...) y
    descarta un paréntesis aclaratorio del nombre declarado ("Monolito modular
    (Monolítica)"). No compara por substring: "Arquitectura" no es
    "Arquitectura hexagonal" ni "CQRS + Event Sourcing" es "Event sourcing".
    """
    # Import diferido: proposal_generator importa este módulo.
    from app.core.proposal_generator import _pattern_aliases

    if not declared or not pattern_name:
        return False
    aliases = {_normalize(alias) for alias in _pattern_aliases(pattern_name)}
    candidates = {declared, _normalize(_PARENTHETICAL_RE.sub("", declared))}
    return bool(candidates & aliases)


def _has_justification(markdown: str) -> bool:
    """La justificación pasa el mismo control que exige producción.

    Usa ``proposal_generator._missing_sections``: el encabezado existe y la
    sección llega hasta su riesgo o costo, así un placeholder (``- ...``) no
    cuenta y el KR no diverge del validador que decide si se guarda la propuesta.
    """
    from app.core.proposal_generator import _missing_sections

    missing = _missing_sections(markdown)
    return "Justificación del patrón principal" not in missing and "Riesgo o costo" not in missing


def _normalize_lines(markdown: str) -> str:
    """Como ``_normalize`` pero conservando los saltos de línea."""
    return "\n".join(_normalize(line) for line in (markdown or "").splitlines())


def analyze_justification(markdown: str | None, citations: Iterable[dict] | None) -> dict:
    """Evalúa si la propuesta cita patrones según la definición del módulo.

    Devuelve un dict nuevo; ``citations`` no se modifica.
    """
    normalized = _normalize_lines(markdown or "")
    primary = _primary_citation(citations or [])
    primary_name = (primary or {}).get("pattern_name")
    declared = _declared_primary(normalized)

    primary_in_sources = bool(
        declared and primary_name and _names_match(declared, primary_name)
    )
    justified = _has_justification(markdown or "")
    return {
        "cites_patterns": primary_in_sources and justified,
        "declared_primary": declared,
        "primary_pattern_id": (primary or {}).get("pattern_id"),
        "primary_pattern_name": primary_name,
        "primary_in_sources": primary_in_sources,
        "justified": justified,
    }


def summarize_citation_rate(
    analyses: Iterable[dict],
    target: float = CITATION_TARGET_RATE,
) -> dict:
    """Agrega análisis de propuestas para el KR (``citation_rate >= target``)."""
    items = list(analyses)
    total = len(items)
    citing = sum(1 for item in items if item.get("cites_patterns"))
    rate = round(citing / total, 4) if total else 0.0
    return {
        "proposals_total": total,
        "proposals_citing": citing,
        "citation_rate": rate,
        "target": target,
        "meets_target": total > 0 and rate >= target,
    }
