from __future__ import annotations
import re

_DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "classDiagram")
_MERMAID_PATTERN = re.compile(r"```mermaid\s*\n([\s\S]*?)```")
# Etiqueta de nodo entre corchetes simples: A[texto]. No captura across
# saltos de linea ni corchetes anidados (suficiente para el caso que nos
# interesa detectar).
_NODE_LABEL_PATTERN = re.compile(r"\[([^\[\]\n]*)\]")


def extract_mermaid_block(text: str) -> str | None:
    match = _MERMAID_PATTERN.search(text)
    return match.group(1).strip() if match else None


def _label_has_unquoted_specials(label: str) -> bool:
    """True si `label` (el texto entre `[` y `]`) rompe el parser de
    Mermaid porque contiene un caracter especial sin comillas.

    Bug real (HU6): ``Cliente[Cliente (Web / Mobile)]`` pasaba el
    validador viejo (parentesis balanceados en TODO el documento) pero
    Mermaid lo rechaza: un ``(`` dentro de una etiqueta ``[...]`` sin
    comillas es un token de "inicio de forma redonda" para el parser,
    no texto literal. El fix es citar la etiqueta: ``["Cliente (Web /
    Mobile)"]``. Se excluye la forma especial ``[(texto)]`` (nodo
    cilindro/base de datos), donde el parentesis SI es sintaxis valida
    porque envuelve la etiqueta completa.
    """
    if label.startswith('"') and label.endswith('"'):
        return False
    if label.startswith("(") and label.endswith(")"):
        # Forma especial (cilindro/DB): A[(texto)] — valido tal cual.
        return False
    return any(ch in label for ch in "()\"")


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

    for match in _NODE_LABEL_PATTERN.finditer(stripped):
        label = match.group(1)
        if _label_has_unquoted_specials(label):
            return False, (
                f"Etiqueta de nodo sin comillas contiene caracteres especiales: "
                f'[{label}]. Envolvé el texto entre comillas: ["{label}"]'
            )

    return True, None