"""HU8 -- justificación de propuestas basada en patrones reconocidos.

Lógica pura (sin DB ni LLM) que conecta el RAG con la propuesta generada:

1. ``build_citations`` convierte los chunks recuperados de PGVector en una
   lista de fuentes numeradas ``[1..n]``, deduplicada por patrón (el RAG
   indexa varios chunks por patrón: summary, tradeoffs, when_not_to_use...)
   y con la información necesaria para que el usuario verifique la fuente.
2. ``analyze_justification`` parsea el markdown que devolvió el LLM, detecta
   cada decisión (bullet dentro de Componentes / Tecnologias / Patrones) y
   calcula qué decisiones citan un patrón del RAG mediante ``[n]``.
3. ``summarize_citation_rate`` agrega el análisis de varias propuestas para
   medir el KR "≥80% de propuestas citan patrones".
"""

from __future__ import annotations

import re
from typing import Iterable

from langchain_core.documents import Document

# KR de Sofía (HU8): al menos el 80% de las propuestas debe citar patrones.
CITATION_TARGET_RATE = 0.8

# Largo del snippet expuesto en el payload SSE / JSONB (contrato F08).
SNIPPET_CHARS = 240

# Secciones de la propuesta cuyas viñetas cuentan como "decisiones".
DECISION_SECTIONS = ("componentes", "tecnologias", "patrones")

CURATED_SOURCE_LABEL = "Catálogo curado de patrones (arch-agent)"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
_CITATION_REF_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _normalize_heading(text: str) -> str:
    """'Tecnologías' / 'TECNOLOGIAS' / 'Tecnologias:' -> 'tecnologias'."""
    replacements = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouaeiou")
    return text.translate(replacements).strip().rstrip(":").lower()


def _source_for(metadata: dict) -> dict:
    """Describe de dónde sale el texto citado para que el usuario lo verifique."""
    filename = metadata.get("source_filename")
    if filename:
        return {
            "type": "source_upload",
            "label": f"Documento fuente: {filename}",
            "filename": filename,
        }
    return {
        "type": "curated_catalog",
        "label": CURATED_SOURCE_LABEL,
        "filename": None,
    }


def build_citations(
    docs: Iterable[Document],
    min_similarity: float,
    max_patterns: int = 5,
) -> list[dict]:
    """Proyecta los documentos del RAG al payload de citas numeradas.

    - Descarta chunks por debajo de ``min_similarity``.
    - Deduplica por ``pattern_id`` (se queda con el chunk más similar).
    - Ordena por similitud descendente y numera desde 1; ese número es el
      que el LLM debe usar como ``[n]`` en la propuesta.
    """
    best_by_pattern: dict[object, Document] = {}
    order: list[object] = []
    for doc in docs:
        similarity = doc.metadata.get("similarity") or 0.0
        if similarity < min_similarity:
            continue
        key = doc.metadata.get("pattern_id")
        if key is None:
            # Sin pattern_id no podemos deduplicar; lo tratamos como único.
            key = ("chunk", len(order))
        current = best_by_pattern.get(key)
        if current is None:
            order.append(key)
            best_by_pattern[key] = doc
        elif similarity > (current.metadata.get("similarity") or 0.0):
            best_by_pattern[key] = doc

    ranked = sorted(
        (best_by_pattern[key] for key in order),
        key=lambda d: d.metadata.get("similarity") or 0.0,
        reverse=True,
    )[:max_patterns]

    citations: list[dict] = []
    for index, doc in enumerate(ranked, start=1):
        metadata = doc.metadata
        pattern_id = metadata.get("pattern_id")
        citations.append(
            {
                "index": index,
                "pattern_id": pattern_id,
                "pattern_name": metadata.get("pattern_name"),
                "category": metadata.get("category"),
                "similarity": metadata.get("similarity"),
                "snippet": (doc.page_content or "")[:SNIPPET_CHARS],
                "chunk_type": metadata.get("chunk_type"),
                "source": _source_for(metadata),
                "verify_url": (
                    f"/api/patterns/{pattern_id}" if pattern_id is not None else None
                ),
                "cited": False,
            }
        )
    return citations


def extract_decisions(markdown: str) -> list[dict]:
    """Devuelve cada viñeta de las secciones de decisión con su sección."""
    decisions: list[dict] = []
    current_section: str | None = None
    for line in (markdown or "").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            normalized = _normalize_heading(heading.group(1))
            current_section = normalized if normalized in DECISION_SECTIONS else None
            continue
        if current_section is None:
            continue
        bullet = _BULLET_RE.match(line)
        if bullet and bullet.group(1).strip() not in {"...", "…"}:
            decisions.append({"section": current_section, "text": bullet.group(1)})
    return decisions


def _referenced_indices(text: str) -> list[int]:
    indices: list[int] = []
    for match in _CITATION_REF_RE.finditer(text):
        for raw in match.group(1).split(","):
            indices.append(int(raw.strip()))
    return indices


def analyze_justification(markdown: str, citations: list[dict]) -> dict:
    """Mide qué decisiones de la propuesta citan un patrón recuperado del RAG.

    Una referencia ``[n]`` solo cuenta si ``n`` corresponde a una cita real;
    referencias a índices inexistentes se reportan en ``invalid_refs`` para
    detectar alucinaciones del LLM.

    Muta ``citations`` marcando ``cited=True`` en las fuentes efectivamente
    referenciadas, de modo que la UI pueda distinguirlas.
    """
    # Citas persistidas antes de HU8 no traen ``index``; el prompt anterior
    # ya las numeraba por posición desde 1, así que se reconstruye igual.
    for position, citation in enumerate(citations, start=1):
        if citation.get("index") is None:
            citation["index"] = position
    valid = {c["index"]: c for c in citations}
    decisions = extract_decisions(markdown)

    cited_indices: set[int] = set()
    invalid_refs: set[int] = set()
    decisions_cited = 0
    uncited: list[dict] = []

    for decision in decisions:
        refs = _referenced_indices(decision["text"])
        good = [ref for ref in refs if ref in valid]
        invalid_refs.update(ref for ref in refs if ref not in valid)
        if good:
            decisions_cited += 1
            cited_indices.update(good)
        else:
            uncited.append(decision)

    # Referencias fuera de las viñetas (p. ej. un párrafo de contexto) también
    # marcan la fuente como citada, aunque no sumen a la cobertura por decisión.
    for ref in _referenced_indices(markdown or ""):
        if ref in valid:
            cited_indices.add(ref)
        else:
            invalid_refs.add(ref)

    for index, citation in valid.items():
        citation["cited"] = index in cited_indices

    total = len(decisions)
    return {
        "decisions_total": total,
        "decisions_cited": decisions_cited,
        "coverage": round(decisions_cited / total, 4) if total else 0.0,
        "cites_patterns": bool(cited_indices),
        "cited_indices": sorted(cited_indices),
        "invalid_refs": sorted(invalid_refs),
        "uncited_decisions": [
            {"section": d["section"], "text": d["text"][:200]} for d in uncited
        ],
    }


def summarize_citation_rate(analyses: Iterable[dict]) -> dict:
    """Agrega análisis por propuesta en la métrica del KR (≥80%)."""
    items = list(analyses)
    total = len(items)
    citing = sum(1 for a in items if a.get("cites_patterns"))
    decisions_total = sum(a.get("decisions_total", 0) for a in items)
    decisions_cited = sum(a.get("decisions_cited", 0) for a in items)
    rate = round(citing / total, 4) if total else 0.0
    return {
        "proposals_total": total,
        "proposals_citing_patterns": citing,
        "citation_rate": rate,
        "decisions_total": decisions_total,
        "decisions_cited": decisions_cited,
        "decision_coverage": (
            round(decisions_cited / decisions_total, 4) if decisions_total else 0.0
        ),
        "target_rate": CITATION_TARGET_RATE,
        "meets_target": total > 0 and rate >= CITATION_TARGET_RATE,
    }
