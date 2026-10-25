"""
Corpus de diagramas Mermaid "tipo LLM" usado como regresión del
sanitizador/validador (`sanitize_mermaid` + `validate_mermaid`,
app/core/mermaid_validator.py), inspirado en el KR de Sofía para F09
("≥75% de los diagramas sin errores").

## Qué prueba esto y qué NO prueba

SÍ prueba: que los quirks de sintaxis ya documentados en HU6 (paréntesis
sin comillas, comillas internas, subgraphs con acentos, `class` mezclando
IDs y etiquetas) siguen siendo rescatados por el sanitizador, y que los
casos que no debe/puede rescatar siguen siendo rechazados por el motivo
esperado (no cualquier motivo). Es un test de regresión del sanitizador:
si alguien lo rompe, esto lo detecta caso por caso.

NO prueba, aunque esté inspirado en él, el KR de Sofía tal como está
redactado. Dos razones:
  1. El corpus no es una muestra de diagramas reales de producción: la
     mayoría de los casos que pasan son justo los bugs para los que se
     escribió el sanitizador (sus propios casos de entrenamiento), así
     que la tasa que da depende de qué fallos eligió incluir quien
     escribió el corpus, no de cómo se comporta el LLM en la práctica.
  2. `validate_mermaid` es una heurística (conteo de corchetes/paréntesis
     + regex), no el parser real de Mermaid.js -- pasar este check no
     garantiza que el diagrama renderice en el navegador.
La medición real del KR es manual/de producción, contando el evento SSE
`diagram_validated` sobre diagramas generados por el LLM real -- ver
`docs/QA_feature-hu6-diagrama.md`, sección 8.

## Otras notas

- Con el corpus actual el margen es de un solo caso: un fallo más
  (12/17 = 70.6%) ya rompe el piso de 75%. No es un margen holgado.
- "3 tipos de diagrama" es como F09 describe el pedido, pero en términos
  de gramática Mermaid acá solo hay 2: flowchart/graph (cubre tanto
  "flujo" como "componentes" -- este último vía subgraphs, según
  `DIAGRAM_HINT` en `agent.py`) y `sequenceDiagram`. El test de cobertura
  de más abajo lo verifica por contenido real (palabra clave inicial /
  presencia de `subgraph`), no por el nombre que se le puso al caso.
- Los casos rechazados por el validador NO son todos "errores de
  sintaxis": `erDiagram` es Mermaid válido, lo rechaza el allowlist
  `_DIAGRAM_TYPES` de esta app (una decisión de producto, no un problema
  de sintaxis); un fence vacío es "el LLM no devolvió nada", un caso
  límite distinto. Solo corchetes/paréntesis sin cerrar son errores de
  sintaxis reales.

Si este test empieza a fallar, revisá primero SI el fallo es esperado
(¿se agregó un caso nuevo con `expected_valid=False` a propósito?) antes
de asumir que el sanitizador se rompió.
"""
from __future__ import annotations

import pytest

from app.core.mermaid_validator import sanitize_mermaid, validate_mermaid

MIN_SUCCESS_RATE = 0.75  # KR Sofía (F09) — grep "MIN_SUCCESS_RATE" para encontrar este umbral

# (case_id, mermaid crudo tipo LLM, expected_valid, substring esperado del
# error si expected_valid=False -- None si expected_valid=True)
CASES: list[tuple[str, str, bool, str | None]] = [
    # -- flowchart / "flujo" ---------------------------------------------
    ("flujo_simple", "flowchart TD\nA[Inicio] --> B[Fin]", True, None),
    (
        "flujo_parens_sin_comillas",
        "flowchart TD\nA[Cliente (Web / Mobile)] --> B[API]",
        True,
        None,
    ),
    (
        "flujo_comillas_internas",
        'flowchart TD\nA[Cliente "Premium"] --> B[API]',
        True,
        None,
    ),
    (
        "flujo_subgraph_acentos",
        "flowchart TD\nsubgraph Servicios_Síncronos\nA-->B\nend",
        True,
        None,
    ),
    (
        "flujo_class_mezclado",
        "flowchart TD\nA-->B\nclass A,B,API Gateway,Orders service",
        True,
        None,
    ),
    ("flujo_db_cilindro", "flowchart TD\nA-->DB[(Base de datos)]", True, None),
    (
        "flujo_completo_arquitectura",
        "flowchart TD\nsubgraph Frontend\nUI[React SPA]\nend\n"
        'subgraph Backend\nAPI["API Gateway"] --> Orders[Servicio de Ordenes]\n'
        "Orders --> DB[(PostgreSQL)]\nend\nUI --> API",
        True,
        None,
    ),
    # -- flowchart con subgraphs: forma en que F09 pide "componentes" ----
    (
        "componentes_microservicios",
        "flowchart LR\nsubgraph Microservicios\n"
        'Gateway["API Gateway"] --> Payments["Servicio de Pagos"]\n'
        'Gateway --> Inventory["Servicio de Inventario"]\nend',
        True,
        None,
    ),
    ("componentes_graph_alias", "graph TD\nA-->B\nB-->C", True, None),
    # (se removió "componentes_con_parens": probaba lo mismo que
    #  "flujo_parens_sin_comillas" -- paréntesis sin comillas rescatados
    #  por el sanitizador -- solo cambiaba el nombre del caso, no el
    #  fenómeno bajo prueba)
    # -- sequenceDiagram / "secuencia" ------------------------------------
    (
        "secuencia_simple",
        "sequenceDiagram\nparticipant U as Usuario\nparticipant A as API\n"
        "U->>A: solicitud\nA-->>U: respuesta",
        True,
        None,
    ),
    (
        "secuencia_con_nota_parens",
        "sequenceDiagram\nparticipant U as Usuario\n"
        "Note over U: 1) validar (paso previo)\nU->>A: ok",
        True,
        None,
    ),
    (
        "secuencia_multi_actor",
        "sequenceDiagram\nparticipant C as Cliente\nparticipant G as Gateway\n"
        "participant O as Orders\nC->>G: crear pedido\nG->>O: procesar\n"
        "O-->>G: confirmado\nG-->>C: 200 OK",
        True,
        None,
    ),
    # -- otro tipo soportado por el validador (bonus, fuera de los 3 que
    #    pide F09 estrictamente). Es un caso válido: sube numerador Y
    #    denominador por igual, no "infla" la tasa en ningún sentido. ---
    (
        "clase_simple",
        "classDiagram\nclass Pedido\nPedido : +id\nPedido : +total",
        True,
        None,
    ),
    # -- rechazados por el validador, pero NO son errores de sintaxis ----
    (
        "no_soportado_tipo_er",
        "erDiagram\nA ||--o{ B : tiene",
        False,
        "no reconocido",
    ),  # erDiagram es Mermaid válido; lo rechaza el allowlist
    # _DIAGRAM_TYPES de esta app, no un problema de sintaxis del diagrama.
    ("entrada_vacia", "   ", False, "vacío"),  # el LLM no devolvió nada
    # -- errores de sintaxis reales (los únicos 2 de la categoría) -------
    (
        "syntax_corchete_sin_cerrar",
        "flowchart TD\nA[Inicio --> B[Fin]",
        False,
        "Corchetes sin cerrar",
    ),
    (
        "syntax_parentesis_sin_cerrar",
        "flowchart TD\nA(Inicio --> B[Fin]",
        False,
        "Paréntesis sin cerrar",
    ),
]


@pytest.mark.parametrize(
    "case_id,raw,expected_valid,expected_error_substring",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_case_matches_expected_validity(
    case_id, raw, expected_valid, expected_error_substring
):
    """Cada caso se verifica por separado: si uno solo cambia de
    comportamiento (empieza a fallar, o empieza a pasar, o falla por otro
    motivo), este test lo señala puntualmente en vez de esconderse detrás
    de una tasa agregada."""
    code = sanitize_mermaid(raw)
    is_valid, error = validate_mermaid(code)

    assert is_valid == expected_valid, (
        f"{case_id}: se esperaba valid={expected_valid}, se obtuvo "
        f"valid={is_valid} (error={error!r})"
    )
    if not expected_valid:
        assert expected_error_substring in (error or ""), (
            f"{case_id}: se esperaba que el error contuviera "
            f"{expected_error_substring!r}, se obtuvo {error!r}"
        )


def test_corpus_success_rate_stays_at_or_above_sofia_kr_floor():
    """Piso de regresión inspirado en el KR de Sofía -- no una medición
    del KR en producción (ver docstring del módulo). Recalcula sobre el
    resultado REAL de cada caso (no sobre `expected_valid`), así que
    también detecta una regresión si se corre este test solo, sin los
    parametrizados de arriba."""
    total = len(CASES)
    valid = 0
    for _, raw, _, _ in CASES:
        code = sanitize_mermaid(raw)
        is_valid, _ = validate_mermaid(code)
        if is_valid:
            valid += 1

    rate = valid / total
    assert rate >= MIN_SUCCESS_RATE, (
        f"Tasa {rate:.1%} ({valid}/{total}) cayó debajo del piso de "
        f"regresión {MIN_SUCCESS_RATE:.0%} (inspirado en el KR de Sofía, "
        f"F09; no es una medición del KR en producción -- ver docstring "
        f"del módulo)."
    )


def test_required_f09_diagram_grammars_have_at_least_one_valid_case():
    """F09 pide 3 tipos de diagrama (flujo, componentes, secuencia); en
    términos de gramática Mermaid son 2: flowchart/graph (flujo Y
    componentes, este último vía subgraphs) y sequenceDiagram. Se
    verifica por contenido real de cada caso -- no por el nombre que se
    le puso -- así que renombrar un caso no rompe la cobertura en
    silencio."""
    has_flowchart = False
    has_flowchart_with_subgraph = False
    has_sequence = False

    for _, raw, expected_valid, _ in CASES:
        if not expected_valid:
            continue
        code = sanitize_mermaid(raw)
        is_valid, _ = validate_mermaid(code)
        if not is_valid:
            continue

        first_line = code.strip().splitlines()[0]
        if first_line.startswith(("flowchart", "graph")):
            has_flowchart = True
            if "subgraph" in code:
                has_flowchart_with_subgraph = True
        elif first_line.startswith("sequenceDiagram"):
            has_sequence = True

    assert has_flowchart, "Ningún caso válido de flowchart/graph (flujo)"
    assert has_flowchart_with_subgraph, (
        "Ningún caso válido de flowchart con subgraph (representación de "
        "'componentes' según DIAGRAM_HINT)"
    )
    assert has_sequence, "Ningún caso válido de sequenceDiagram (secuencia)"
