from __future__ import annotations
import re
import unicodedata

_DIAGRAM_TYPES = ("flowchart", "graph", "sequenceDiagram", "classDiagram")
_MERMAID_PATTERN = re.compile(r"```mermaid\s*\n([\s\S]*?)```")
_FENCED_CODE_PATTERN = re.compile(r"```[^\n]*\n([\s\S]*?)```")
# Etiqueta de nodo entre corchetes simples: A[texto]. No captura across
# saltos de linea ni corchetes anidados (suficiente para el caso que nos
# interesa detectar).
_NODE_LABEL_PATTERN = re.compile(r"\[([^\[\]\n]*)\]")


def extract_mermaid_block(text: str) -> str | None:
    match = _MERMAID_PATTERN.search(text)
    if match:
        return match.group(1).strip()

    for candidate in _FENCED_CODE_PATTERN.finditer(text):
        code = candidate.group(1).strip()
        first_line = code.splitlines()[0] if code else ""
        if any(first_line.startswith(t) for t in _DIAGRAM_TYPES):
            return code

    return None


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


def sanitize_mermaid_labels(code: str) -> str:
    """Auto-corrige labels de nodo que romperian el parser de Mermaid,
    envolviendolos en comillas. Se llama ANTES de validate_mermaid()
    para que el caso comun (parentesis/barras sin comillas) no llegue
    a rechazarse.
    """
    def _fix(match: re.Match) -> str:
        label = match.group(1)
        if _label_has_unquoted_specials(label):
            return f'["{label}"]'
        return match.group(0)

    return _NODE_LABEL_PATTERN.sub(_fix, code)


_CLASS_STATEMENT_PATTERN = re.compile(r"^(\s*class\s+)([^;\n]+?)(\s+\w+\s*;?\s*)$", re.MULTILINE)
_VALID_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUBGRAPH_PATTERN = re.compile(r"^(\s*subgraph\s+)(.+?)\s*$", re.MULTILINE)


def _slug_mermaid_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", ascii_only).strip("_")
    if not slug:
        slug = "Subgraph"
    if not re.match(r"^[A-Za-z_]", slug):
        slug = f"_{slug}"
    return slug


def sanitize_class_statements(code: str) -> str:
    """Corrige sentencias `class` invalidas.

    Bug real (visto en produccion): el LLM a veces mezcla, en la misma
    linea `class`, IDs cortos de nodo (validos) con las ETIQUETAS del
    nodo (invalido, rompe el parser en cuanto aparece un espacio):

        class B,G,F,API Gateway,Microservicio Orders service

    Mermaid solo acepta IDs de nodo (sin espacios) en esa lista. Esta
    funcion filtra cada lista `class X,Y,Z nombreClase`, descartando
    cualquier token que no sea un identificador valido (con espacios,
    con simbolos, etc.). Si no queda ningun ID valido, se elimina la
    linea entera (mejor sin colorear esos nodos que romper el diagrama
    completo).
    """
    def _fix(match: re.Match) -> str:
        prefix, ids_part, suffix = match.group(1), match.group(2), match.group(3)
        tokens = [t.strip() for t in ids_part.split(",")]
        valid = [t for t in tokens if _VALID_ID_PATTERN.match(t)]
        if not valid:
            return ""  # elimina la linea completa
        return f"{prefix}{','.join(valid)}{suffix}"

    return _CLASS_STATEMENT_PATTERN.sub(_fix, code)


def sanitize_subgraph_statements(code: str) -> str:
    """Convierte subgraphs con IDs no compatibles a ID seguro + label.

    Mermaid puede rechazar lineas como ``subgraph Servicios_Síncronos``
    porque el identificador interno contiene acentos. La forma robusta es
    ``subgraph Servicios_Sincronos["Servicios_Síncronos"]``: el ID queda
    ASCII y la etiqueta visible conserva el texto original.
    """
    def _fix(match: re.Match) -> str:
        prefix, raw = match.group(1), match.group(2).strip()

        # Si ya usa una forma avanzada/rotulada, no tocamos la linea.
        if any(ch in raw for ch in "[]\""):
            return match.group(0)

        if _VALID_ID_PATTERN.match(raw):
            return match.group(0)

        safe_id = _slug_mermaid_id(raw)
        label = raw.replace('"', '\\"')
        return f'{prefix}{safe_id}["{label}"]'

    return _SUBGRAPH_PATTERN.sub(_fix, code)


def sanitize_mermaid(code: str) -> str:
    """Aplica todos los sanitizadores conocidos, en orden."""
    code = sanitize_mermaid_labels(code)
    code = sanitize_subgraph_statements(code)
    code = sanitize_class_statements(code)
    return code


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
