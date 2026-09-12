from __future__ import annotations
import re

_DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "classDiagram")
_MERMAID_PATTERN = re.compile(r"```mermaid\s*\n([\s\S]*?)```")


def extract_mermaid_block(text: str) -> str | None:
    match = _MERMAID_PATTERN.search(text)
    return match.group(1).strip() if match else None


def validate_mermaid(code: str) -> tuple[bool, str | None]:
    stripped = code.strip()
    if not stripped:
        return False, "Bloque mermaid vacío"

    first_line = stripped.splitlines()[0]
    if not any(first_line.startswith(t) for t in _DIAGRAM_TYPES):
        return False, f"Tipo de diagrama no reconocido: '{first_line}'"

    if stripped.count("[") != stripped.count("]"):
        return False, "Corchetes sin cerrar"
    if stripped.count("(") != stripped.count(")"):
        return False, "Paréntesis sin cerrar"

    return True, None