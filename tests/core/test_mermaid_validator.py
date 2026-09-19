from app.core.mermaid_validator import (
    extract_mermaid_block,
    sanitize_class_statements,
    sanitize_mermaid,
    sanitize_mermaid_labels,
    sanitize_subgraph_statements,
    validate_mermaid,
)


def test_extract_mermaid_block_from_explicit_mermaid_fence():
    text = "```mermaid\nflowchart TD\nA-->B\n```"

    assert extract_mermaid_block(text) == "flowchart TD\nA-->B"


def test_extract_mermaid_block_from_plain_fence_when_content_is_mermaid():
    text = "```text\nflowchart TD\nA[Cliente]-->B[API]\n```"

    assert extract_mermaid_block(text) == "flowchart TD\nA[Cliente]-->B[API]"


def test_extract_mermaid_block_ignores_non_diagram_plain_code():
    text = "```python\nprint('hola')\n```"

    assert extract_mermaid_block(text) is None


# ---------------------------------------------------------------------------
# sanitize_mermaid_labels (hallazgos #3 y #5, revisión feature/hu6-diagrama)
# ---------------------------------------------------------------------------


def test_sanitize_mermaid_labels_quotes_parens_and_slash_in_flowchart():
    """Bug real HU6: `Cliente[Cliente (Web / Mobile)]` rompía el parser de
    Mermaid porque `(` dentro de una etiqueta sin comillas es sintaxis de
    nodo redondo, no texto literal."""
    code = "flowchart TD\nA[Cliente (Web / Mobile)]-->B[API]"

    result = sanitize_mermaid_labels(code)

    assert result == 'flowchart TD\nA["Cliente (Web / Mobile)"]-->B[API]'


def test_sanitize_mermaid_labels_escapes_internal_quotes():
    """Hallazgo #5: citar sin escapar comillas internas producía
    `["Cliente "Premium""]`, invalido porque la comilla interna cierra el
    string a mitad de camino."""
    code = 'flowchart TD\nA[Cliente "Premium"]-->B'

    result = sanitize_mermaid_labels(code)

    assert result == 'flowchart TD\nA["Cliente #quot;Premium#quot;"]-->B'
    # La comilla escapada no debe dejar un string mal cerrado: el label
    # entero sigue empezando y terminando con exactamente una comilla.
    label = result.splitlines()[1]
    assert label.count('"') == 2


def test_sanitize_mermaid_labels_leaves_already_quoted_label_untouched():
    code = 'flowchart TD\nA["ya citado (con parentesis)"]-->B'

    assert sanitize_mermaid_labels(code) == code


def test_sanitize_mermaid_labels_leaves_db_cylinder_shape_untouched():
    """`[(texto)]` es la forma especial de nodo cilindro/DB -- el paréntesis
    ahí SÍ es sintaxis válida y no debe citarse."""
    code = "flowchart TD\nA[(orders_db)]-->B[API]"

    assert sanitize_mermaid_labels(code) == code


def test_sanitize_mermaid_labels_ignores_non_flowchart_diagram_types():
    """Hallazgo #3: antes este sanitizador corría sobre CUALQUIER tipo de
    diagrama y corrompía sintaxis válida de sequenceDiagram (donde `[...]`
    dentro de un mensaje no es una etiqueta de nodo)."""
    code = "sequenceDiagram\nA->>B: parse items[0](x)"

    assert sanitize_mermaid_labels(code) == code


# ---------------------------------------------------------------------------
# sanitize_class_statements (hallazgo #3)
# ---------------------------------------------------------------------------


def test_sanitize_class_statements_drops_non_id_tokens_in_flowchart():
    code = "flowchart TD\nclass B,G,F,API Gateway,Microservicio Orders service"

    result = sanitize_class_statements(code)

    assert result == "flowchart TD\nclass B,G,F service"


def test_sanitize_class_statements_drops_whole_line_when_no_valid_ids():
    """Mejor sin colorear esos nodos que romper el diagrama completo."""
    code = "flowchart TD\nclass API Gateway,Order Service styled"

    result = sanitize_class_statements(code)

    assert result == "flowchart TD\n"
    assert "class" not in result


def test_sanitize_class_statements_ignores_non_flowchart_diagram_types():
    """Hallazgo #3: en classDiagram, una linea `class Foo` es sintaxis
    valida de OTRO tipo (declaracion de clase) -- este sanitizador no debe
    tocarla."""
    code = "classDiagram\nclass Foo\nFoo : +method()"

    assert sanitize_class_statements(code) == code


# ---------------------------------------------------------------------------
# sanitize_subgraph_statements (hallazgo #3)
# ---------------------------------------------------------------------------


def test_sanitize_subgraph_statements_slugs_accented_id_and_keeps_label():
    code = "flowchart TD\nsubgraph Servicios_Síncronos\nA-->B\nend"

    result = sanitize_subgraph_statements(code)

    assert 'subgraph Servicios_Sincronos["Servicios_Síncronos"]' in result
    assert "A-->B" in result
    assert "end" in result


def test_sanitize_subgraph_statements_leaves_valid_ascii_id_untouched():
    code = "flowchart TD\nsubgraph Servicios\nA-->B\nend"

    assert sanitize_subgraph_statements(code) == code


def test_sanitize_subgraph_statements_leaves_already_labeled_form_untouched():
    code = 'flowchart TD\nsubgraph Servicios["Servicios Síncronos"]\nA-->B\nend'

    assert sanitize_subgraph_statements(code) == code


def test_sanitize_subgraph_statements_ignores_non_flowchart_diagram_types():
    code = "sequenceDiagram\nsubgraph Servicios_Síncronos\nA->>B: hola"

    assert sanitize_subgraph_statements(code) == code


def test_sanitize_mermaid_runs_all_sanitizers_in_order():
    code = (
        "flowchart TD\n"
        "subgraph Servicios_Síncronos\n"
        'A[Cliente (Web / Mobile)]-->B[API]\n'
        "class A,B Órdenes Servicio styled\n"
        "end"
    )

    result = sanitize_mermaid(code)

    assert 'subgraph Servicios_Sincronos["Servicios_Síncronos"]' in result
    assert 'A["Cliente (Web / Mobile)"]-->B[API]' in result
    # "B Órdenes Servicio" no es un token de ID válido (tiene espacios y
    # tildes) y se descarta del listado; solo sobrevive "A".
    assert "class A styled" in result
    assert "Órdenes" not in result


# ---------------------------------------------------------------------------
# validate_mermaid (hallazgo #3: chequeo de labels acotado por tipo)
# ---------------------------------------------------------------------------


def test_validate_mermaid_rejects_unquoted_specials_in_flowchart_label():
    code = "flowchart TD\nA[Cliente (Web / Mobile)]-->B"

    is_valid, error = validate_mermaid(code)

    assert is_valid is False
    assert "Cliente (Web / Mobile)" in error


def test_validate_mermaid_accepts_quoted_label_with_specials():
    code = 'flowchart TD\nA["Cliente (Web / Mobile)"]-->B'

    assert validate_mermaid(code) == (True, None)


def test_validate_mermaid_accepts_db_cylinder_shape():
    code = "flowchart TD\nA[(orders_db)]-->B[API]"

    assert validate_mermaid(code) == (True, None)


def test_validate_mermaid_does_not_apply_label_check_to_sequence_diagram():
    """Hallazgo #3: antes el validador aplicaba el mismo chequeo de
    `[...]` a cualquier tipo de diagrama. En un sequenceDiagram,
    `items[0](x)` dentro de un mensaje es válido para Mermaid y no debe
    rechazarse."""
    code = "sequenceDiagram\nA->>B: parse items[0](x)"

    assert validate_mermaid(code) == (True, None)


def test_validate_mermaid_does_not_check_bracket_balance_outside_flowchart():
    """Hallazgo #3 (corrección post-revisión): el chequeo de balance de
    `[]`/`()` es sintaxis de nodo de flowchart/graph, igual que el chequeo
    de labels -- en un sequenceDiagram, `[`/`(` sin cerrar dentro del
    texto de un mensaje no rompe el parser de Mermaid (no es sintaxis de
    nodo ahí), así que no debe rechazarse.

    (Reemplaza a `test_validate_mermaid_still_checks_bracket_balance_for_any_type`,
    que quedó de una versión anterior del fix y afirmaba justo el
    comportamiento contrario al que pedía el hallazgo #3 -- el test fallaba
    contra la implementación real.)"""
    code = "sequenceDiagram\nA->>B: parse items[0"

    assert validate_mermaid(code) == (True, None)


def test_validate_mermaid_still_checks_bracket_balance_in_flowchart():
    code = "flowchart TD\nA[Cliente-->B"

    is_valid, error = validate_mermaid(code)

    assert is_valid is False
    assert "Corchetes" in error


def test_validate_mermaid_rejects_empty_block():
    assert validate_mermaid("") == (False, "Bloque mermaid vacío")
    assert validate_mermaid("   \n  ") == (False, "Bloque mermaid vacío")


def test_validate_mermaid_rejects_unrecognized_diagram_type():
    is_valid, error = validate_mermaid("notadiagram\nfoo-->bar")

    assert is_valid is False
    assert "no reconocido" in error
