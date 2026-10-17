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


_FLOWCHART_TYPES = ("flowchart", "graph")


def _diagram_type(code: str) -> str:
    stripped = code.strip()
    first_line = stripped.splitlines()[0] if stripped else ""
    return first_line.strip()


def sanitize_mermaid_labels(code: str) -> str:
    """Auto-corrige labels de nodo que romperian el parser de Mermaid,
    envolviendolos en comillas. Se llama ANTES de validate_mermaid()
    para que el caso comun (parentesis/barras sin comillas) no llegue
    a rechazarse.

    Solo aplica a diagramas de flujo (`flowchart`/`graph`): `[...]` es
    sintaxis de nodo unicamente ahi. En `sequenceDiagram` o
    `classDiagram`, corchetes con ese mismo texto tienen otro
    significado (p. ej. mensajes o anotaciones), y aplicar este regex
    sobre todo el documento corrompia esa sintaxis (bug real, HU6).
    """
    first_line = _diagram_type(code)
    if not any(first_line.startswith(t) for t in _FLOWCHART_TYPES):
        return code

    def _fix(match: re.Match) -> str:
        label = match.group(1)
        if _label_has_unquoted_specials(label):
            # Hallazgo #5 (revisión feature/hu6-diagrama): antes se citaba
            # el label sin escapar comillas internas, así que
            # `Cliente "Premium"` quedaba `["Cliente "Premium""]` -- una
            # comilla que cierra el string a mitad de camino, inválido para
            # Mermaid aunque `_label_has_unquoted_specials` lo diera por
            # bueno (empieza y termina con `"`). Se escapan con `#quot;`,
            # la entidad que Mermaid soporta dentro de labels citados.
            escaped = label.replace('"', "#quot;")
            return f'["{escaped}"]'
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


def _is_flowchart(code: str) -> bool:
    first_line = _diagram_type(code)
    return any(first_line.startswith(t) for t in _FLOWCHART_TYPES)


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
    # Hallazgo #3 (revisión feature/hu6-diagrama): igual que
    # sanitize_mermaid_labels, esto solo tiene sentido para
    # flowchart/graph -- en sequenceDiagram/classDiagram una línea que
    # empiece con "class " puede ser sintaxis válida de otro tipo (p. ej.
    # una clase de classDiagram) y este regex la corrompía igual.
    if not _is_flowchart(code):
        return code

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
    # Hallazgo #3: `subgraph` es sintaxis de flowchart/graph. Igual que los
    # otros sanitizadores, se acota para no tocar contenido de otros tipos
    # de diagrama que pudiera coincidir por casualidad con este patrón.
    if not _is_flowchart(code):
        return code

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


# Flecha con etiqueta al estilo de stateDiagram (``A --> B : "texto"``), que
# los modelos escriben a menudo dentro de un flowchart. En flowchart es un error
# de sintaxis y el diagrama no se puede renderizar; la forma válida es
# ``A -->|texto| B``.
#
# El nodo puede llevar una clase (``B:::svc``). Antes ``dst`` cortaba en el
# primer ``:`` y ``A --> B:::svc`` se convertía en ``A -->|::svc| B``. Ahora la
# clase es parte del nodo y el ``:`` de la etiqueta no puede ir seguido de otro.
_NODE_WITH_CLASS = r"[^\s:|]+(?::::[\w-]+)?"
_EDGE_WITH_COLON_LABEL = re.compile(
    r"^(?P<indent>\s*)(?P<src>" + _NODE_WITH_CLASS + r")\s*"
    r"(?P<arrow>-->|---|-\.->|==>|--x|--o)\s*"
    r"(?P<dst>" + _NODE_WITH_CLASS + r")\s*:(?!:)\s*(?P<label>.+?)\s*;?\s*$"
)


def sanitize_flowchart_edge_labels(code: str) -> str:
    """Convierte ``A --> B : "texto"`` en ``A -->|texto| B`` en flowcharts.

    Solo toca líneas que son exactamente una flecha con etiqueta tras ``:``;
    el resto del diagrama queda igual. No aplica a otros tipos de diagrama,
    donde ``:`` sí es sintaxis válida (``sequenceDiagram``, ``classDiagram``).
    """
    if not _is_flowchart(code):
        return code

    def _fix(line: str) -> str:
        match = _EDGE_WITH_COLON_LABEL.match(line)
        if match is None:
            return line
        label = match.group("label").strip().strip('"').strip("'").strip()
        # `|` cerraría la etiqueta antes de tiempo; las comillas sueltas rompen el parser.
        label = label.replace("|", "/").replace('"', "#quot;")
        if not label:
            return f"{match.group('indent')}{match.group('src')} {match.group('arrow')} {match.group('dst')}"
        return (
            f"{match.group('indent')}{match.group('src')} {match.group('arrow')}"
            f"|{label}| {match.group('dst')}"
        )

    return "\n".join(_fix(line) for line in code.split("\n"))


_SUBGRAPH_ID_PATTERN = re.compile(r"^(\s*subgraph\s+)([A-Za-z_][A-Za-z0-9_]*)(.*)$")
# Línea que declara un nodo: solo el id, con o sin forma (``X``, ``X["texto"]``,
# ``X(...)``, ``X{...}``, ``X[(...)]``, ``X((...))``), sin flechas.
_NODE_DECLARATION_PATTERN = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:[\[({>].*)?;?\s*$"
)


def sanitize_subgraph_id_collisions(code: str) -> str:
    """Renombra el id de un subgraph cuando hay un nodo declarado con el mismo id.

    Los modelos escriben ``subgraph Vacunas["Módulo de Vacunas"]`` y dentro el
    nodo ``Vacunas``: Mermaid lo rechaza ("Setting Vacunas as parent of
    Vacunas would create a cycle") y el diagrama no se renderiza. Se renombra
    solo el subgraph (``Vacunas_grupo``) y se conserva su etiqueta, así las
    flechas siguen apuntando al nodo. Si el id no se declara como nodo (solo
    aparece en flechas), se deja: esas flechas apuntan al subgraph a propósito.
    """
    if not _is_flowchart(code):
        return code

    lines = code.split("\n")
    subgraph_ids = {
        m.group(2) for line in lines if (m := _SUBGRAPH_ID_PATTERN.match(line))
    }
    if not subgraph_ids:
        return code

    keywords = {"end", "direction", "subgraph", "flowchart", "graph", "class", "classDef", "style", "click", "linkStyle"}
    declared_nodes = set()
    for line in lines:
        if _SUBGRAPH_ID_PATTERN.match(line) or "--" in line or "==" in line:
            continue
        m = _NODE_DECLARATION_PATTERN.match(line)
        if m and m.group(1) not in keywords:
            declared_nodes.add(m.group(1))

    collisions = subgraph_ids & declared_nodes
    if not collisions:
        return code

    taken = subgraph_ids | declared_nodes

    def _new_id(old: str) -> str:
        candidate, n = f"{old}_grupo", 2
        while candidate in taken:
            candidate, n = f"{old}_grupo{n}", n + 1
        taken.add(candidate)
        return candidate

    renames = {old: _new_id(old) for old in sorted(collisions)}

    def _fix(line: str) -> str:
        m = _SUBGRAPH_ID_PATTERN.match(line)
        if not m or m.group(2) not in renames:
            return line
        rest = m.group(3)
        # Sin etiqueta propia, el título visible seguiría siendo el id original.
        if not rest.strip().startswith("["):
            rest = f'["{m.group(2)}"]{rest}'
        return f"{m.group(1)}{renames[m.group(2)]}{rest}"

    return "\n".join(_fix(line) for line in lines)


def sanitize_mermaid(code: str) -> str:
    """Aplica todos los sanitizadores conocidos, en orden."""
    code = sanitize_flowchart_edge_labels(code)
    code = sanitize_subgraph_id_collisions(code)
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

    # Hallazgo #3 (revisión feature/hu6-diagrama): el balance de []/() y el
    # chequeo de labels sin comillas solo tienen sentido en flowchart/graph.
    # Antes se aplicaban a cualquier tipo de diagrama, y en un sequenceDiagram
    # con algo como "Note over A: 1) validar" (un ")" sin "(" en todo el
    # documento) el diagrama se rechazaba aunque Mermaid sí lo renderizara.
    if _is_flowchart(code):
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