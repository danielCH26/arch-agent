"""
KR Sofía (F09): "≥75% de los diagramas sin errores".

Este test prueba esa métrica de forma automatizada y repetible en CI, sin
depender de Docker/Puppeteer ni de un LLM real: corre la MISMA pipeline
determinística que corre en producción antes de intentar el render
(`sanitize_mermaid` + `validate_mermaid`, invocada en `agent.py` justo
después de que el LLM devuelve el bloque ```mermaid```). Un fallo acá es
un fallo real de sintaxis -- no un problema de infraestructura de render.

El corpus junta los 3 tipos de diagrama que pide F09 (flujo, componentes,
secuencia) con los quirks reales que el LLM produce, documentados en HU6:
paréntesis/barras sin comillas, comillas internas en un label, subgraphs
con acentos, `class` mezclando IDs y etiquetas -- casos que el sanitizador
debe rescatar. Se incluyen también fallos genuinos que el sanitizador NO
puede arreglar (tipo de diagrama no soportado, bloque vacío, corchetes o
paréntesis realmente sin cerrar) para que el umbral del 75% sea una
prueba real, no un 100% inflado con solo casos fáciles.

Si este test empieza a fallar, es señal real de que el KR se está
incumpliendo -- no lo subas de umbral para que pase; en su lugar, revisá
qué categoría de fallo creció y si el sanitizador necesita un caso nuevo
(mismo patrón que `mermaid_validator.py`: agregar un `sanitize_*` nuevo,
no relajar `validate_mermaid`).
"""
from __future__ import annotations

from app.core.mermaid_validator import sanitize_mermaid, validate_mermaid

MIN_SUCCESS_RATE = 0.75  # KR Sofía (F09)

# (id del caso, mermaid "crudo" tal como podría salir del LLM)
CORPUS: list[tuple[str, str]] = [
    # -- flujo ----------------------------------------------------------
    ("flujo_simple", "flowchart TD\nA[Inicio] --> B[Fin]"),
    ("flujo_parens_sin_comillas", "flowchart TD\nA[Cliente (Web / Mobile)] --> B[API]"),
    ("flujo_comillas_internas", 'flowchart TD\nA[Cliente "Premium"] --> B[API]'),
    ("flujo_subgraph_acentos", "flowchart TD\nsubgraph Servicios_Síncronos\nA-->B\nend"),
    ("flujo_class_mezclado", "flowchart TD\nA-->B\nclass A,B,API Gateway,Orders service"),
    ("flujo_db_cilindro", "flowchart TD\nA-->DB[(Base de datos)]"),
    (
        "flujo_completo_arquitectura",
        "flowchart TD\nsubgraph Frontend\nUI[React SPA]\nend\n"
        'subgraph Backend\nAPI["API Gateway"] --> Orders[Servicio de Ordenes]\n'
        "Orders --> DB[(PostgreSQL)]\nend\nUI --> API",
    ),
    # -- componentes (arquitectura -> flowchart con subgraphs) ---------
    (
        "componentes_microservicios",
        "flowchart LR\nsubgraph Microservicios\n"
        'Gateway["API Gateway"] --> Payments["Servicio de Pagos"]\n'
        'Gateway --> Inventory["Servicio de Inventario"]\nend',
    ),
    ("componentes_con_parens", "flowchart LR\nA[Auth (JWT)] --> B[API Gateway]"),
    ("componentes_graph_alias", "graph TD\nA-->B\nB-->C"),
    # -- secuencia --------------------------------------------------------
    (
        "secuencia_simple",
        "sequenceDiagram\nparticipant U as Usuario\nparticipant A as API\n"
        "U->>A: solicitud\nA-->>U: respuesta",
    ),
    (
        "secuencia_con_nota_parens",
        "sequenceDiagram\nparticipant U as Usuario\n"
        "Note over U: 1) validar (paso previo)\nU->>A: ok",
    ),
    (
        "secuencia_multi_actor",
        "sequenceDiagram\nparticipant C as Cliente\nparticipant G as Gateway\n"
        "participant O as Orders\nC->>G: crear pedido\nG->>O: procesar\n"
        "O-->>G: confirmado\nG-->>C: 200 OK",
    ),
    # -- otro tipo soportado (bonus, no pedido por F09 pero validado) ---
    ("clase_simple", "classDiagram\nclass Pedido\nPedido : +id\nPedido : +total"),
    # -- fallos genuinos que el sanitizador NO puede rescatar -----------
    ("fallo_tipo_no_reconocido", "erDiagram\nA ||--o{ B : tiene"),
    ("fallo_bloque_vacio", "   "),
    ("fallo_corchete_sin_cerrar", "flowchart TD\nA[Inicio --> B[Fin]"),
    ("fallo_parentesis_sin_cerrar", "flowchart TD\nA(Inicio --> B[Fin]"),
]


def test_diagram_corpus_meets_sofia_kr_syntax_success_rate():
    results: dict[str, tuple[bool, str | None]] = {}
    for name, raw in CORPUS:
        code = sanitize_mermaid(raw)
        is_valid, error = validate_mermaid(code)
        results[name] = (is_valid, error)

    total = len(results)
    valid = sum(1 for is_valid, _ in results.values() if is_valid)
    rate = valid / total

    failures = {name: err for name, (ok, err) in results.items() if not ok}

    assert rate >= MIN_SUCCESS_RATE, (
        f"Tasa de éxito {rate:.1%} ({valid}/{total}) por debajo del "
        f"{MIN_SUCCESS_RATE:.0%} exigido (KR Sofía, F09). Fallos: {failures}"
    )


def test_each_diagram_type_required_by_f09_has_at_least_one_passing_case():
    """F09 pide explícitamente 3 tipos: flujo, componentes, secuencia.
    Este test es más específico que la tasa global: si alguien rompe el
    soporte de UN tipo completo (p. ej. sequenceDiagram) mientras el
    resto compensa la tasa global, este test lo detecta igual."""
    by_prefix = {"flujo": False, "componentes": False, "secuencia": False}
    for name, raw in CORPUS:
        prefix = name.split("_", 1)[0]
        if prefix not in by_prefix:
            continue
        code = sanitize_mermaid(raw)
        is_valid, _ = validate_mermaid(code)
        if is_valid:
            by_prefix[prefix] = True

    missing = [tipo for tipo, ok in by_prefix.items() if not ok]
    assert not missing, f"Ningún caso válido para: {missing}"
