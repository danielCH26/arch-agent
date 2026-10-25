"""Aviso de la revisión automática de una modificación de la propuesta.

Problema: un ajuste que no menciona el patrón (o una tecnología) podía
deshacer una corrección de una iteración anterior. En la prueba del
observatorio, la iteración 2 pidió el pipeline ETL, la 3 no lo nombró y
volvió Monolito modular, con componentes de ETL y patrón monolito: el
documento quedó contradictorio y nadie lo avisó.

``modification_warnings`` compara, sin LLM, la versión anterior con la nueva:

* el patrón principal cambió y el comentario no lo pidió;
* desaparecieron tecnologías que estaban y el comentario no pidió quitarlas;
* la recomendación de la tabla no es el patrón principal (incoherencia
  interna).

El aviso va al principio de la propuesta guardada (``with_modification_note``)
para que el usuario lo vea antes de aprobar. Se quita al usar esa versión
como base de la siguiente modificación y al copiarla en el ADR
(``strip_modification_note``).
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.text_norm import normalize_text

NOTE_TITLE = "### ⚠️ Revisión automática de esta modificación"
_NOTE_TITLE_NORMALIZED = "revision automatica de esta modificacion"

_PRIMARY_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*patr[oó]n\s+principal[*_]*\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_RECOMMENDATION_RE = re.compile(
    r"^\s*[-*+]?\s*[*_]*recomendaci[oó]n[*_]*\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)
_CHANGE_VERBS = re.compile(
    r"\b(?:cambi\w*|reemplaz\w*|sustitu\w*|migr\w*|pasa\w*\s+a|usa\w*|utiliz\w*|en\s+vez\s+de|"
    r"en\s+lugar\s+de|quit\w*|elimin\w*|sin\s+)\b"
)
_STOP = {
    "arquitectura", "patron", "principal", "por", "los", "las", "del", "con", "para",
    "una", "uno", "que", "como", "sobre", "the", "and",
}


def _clean(text: str) -> str:
    text = re.sub(r"\[\d+\]", "", text or "")
    return re.sub(r"[*_`]", "", text).strip(" .-")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", normalize_text(text)) if w not in _STOP}


def _same_pattern(a: str, b: str) -> bool:
    """¿Los dos textos nombran el mismo patrón? (comparten la mayoría de palabras)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return True  # no hay con qué comparar: no se avisa
    common = wa & wb
    return len(common) >= min(2, len(wa), len(wb))


def _technologies(markdown: str) -> list[str]:
    """Primera columna de la tabla de ``## Tecnologias`` (o sus bullets)."""
    lines = (markdown or "").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^\s*#{1,6}\s*[*_\d.)\s]*tecnolog", normalize_text(line))),
        None,
    )
    if start is None:
        return []
    names: list[str] = []
    for line in lines[start + 1 :]:
        if re.match(r"^\s*#{1,6}\s", line):
            break
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            first = _clean(cells[0]) if cells else ""
            if first and not re.fullmatch(r":?-{3,}:?", first) and normalize_text(first) != "tecnologia":
                names.append(first)
        elif re.match(r"^[-*+]\s+", stripped):
            item = _clean(re.sub(r"^[-*+]\s+", "", stripped))
            item = item.split(":", 1)[1] if ":" in item else item
            item = _clean(item.split(" - ")[0].split("(")[0])
            if item:
                names.append(item)
    return names


def modification_warnings(prior: Optional[str], new: str, feedback: Optional[str]) -> list[str]:
    """Lo que la modificación cambió o quitó sin que el comentario lo pidiera."""
    if not prior or not new:
        return []
    prior = strip_modification_note(prior)
    feedback_text = normalize_text(feedback)
    warnings: list[str] = []

    old_primary = _PRIMARY_RE.search(prior)
    new_primary = _PRIMARY_RE.search(new)
    if old_primary and new_primary:
        old_name, new_name = _clean(old_primary.group(1)), _clean(new_primary.group(1))
        asked = bool(_CHANGE_VERBS.search(feedback_text)) and bool(_words(new_name) & _words(feedback_text))
        if not _same_pattern(old_name, new_name) and not asked:
            warnings.append(
                f"El patrón principal cambió de «{old_name}» a «{new_name}» y tu comentario no lo "
                f"pidió. Si no querías cambiarlo, pide «mantén {old_name}»."
            )

    new_text = normalize_text(new)
    dropped = [
        name
        for name in _technologies(prior)
        if normalize_text(name) not in new_text
        and not (_words(name) and _words(name) <= set(re.findall(r"[a-z0-9]{3,}", new_text)))
        and not (_words(name) & _words(feedback_text))
    ]
    if dropped:
        warnings.append(
            "Ya no aparecen tecnologías que estaban en la versión anterior y tu comentario no pidió "
            f"quitar: {', '.join(dropped[:5])}."
        )

    recommendation = _RECOMMENDATION_RE.search(new)
    if new_primary and recommendation and not _same_pattern(
        _clean(new_primary.group(1)), _clean(recommendation.group(1))
    ):
        warnings.append(
            f"La recomendación de la tabla («{_clean(recommendation.group(1))}») no es el patrón "
            f"principal («{_clean(new_primary.group(1))}»): el documento se contradice."
        )
    return warnings


def with_modification_note(markdown: str, warnings: list[str]) -> str:
    """La propuesta con el aviso al principio (sin aviso si no hay nada que decir)."""
    if not warnings:
        return markdown
    note = (
        f"{NOTE_TITLE}\n"
        + "\n".join(f"- {w}" for w in warnings)
        + "\n- Revisa estos puntos antes de aprobar; puedes pedir el cambio con otro comentario.\n\n"
    )
    return note + strip_modification_note(markdown).lstrip()


def strip_modification_note(markdown: Optional[str]) -> str:
    """Quita el aviso (título, su lista y la línea en blanco) si lo hay."""
    text = markdown or ""
    lines = text.splitlines()
    if not lines or _NOTE_TITLE_NORMALIZED not in normalize_text(lines[0]):
        return text
    index = 1
    while index < len(lines) and lines[index].lstrip().startswith("- "):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    rest = "\n".join(lines[index:])
    return rest + ("\n" if text.endswith("\n") and rest else "")
