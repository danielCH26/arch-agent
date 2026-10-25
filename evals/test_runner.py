"""
Tests del golden set.

Todo corre offline: no hay red, ni API key, ni base de datos. El scorer es una
funcion pura y el runner se ejercita con un chat falso, asi que estos tests son
deterministas y valen como puerta de calidad en CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

from evals.runner import (
    SECCIONES_REQUERIDAS,
    _contenido,
    _es_rate_limit,
    _filtrar_peores,
    _jaccard,
    calcular_variabilidad,
    cargar_casos,
    construir_modelo,
    dry_run,
    main,
    marcadores_cita,
    resolver_proveedor,
    resumir_por_modelo,
    score_output,
)


# --- Fixtures ---------------------------------------------------------------

SALIDA_PERFECTA = (
    "## Componentes\n"
    "- API de pedidos [1]\n"
    "- Worker de facturacion [2]\n\n"
    "## Tecnologías\n"
    "- Python\n"
    "- PostgreSQL\n\n"
    "## Patrones\n"
    "- Arquitectura en capas (Layered) [1]\n\n"
    "## Justificación del patrón principal\n"
    "- El dominio cambia seguido, así que la lógica queda aislada [1]\n"
    "- Riesgo: cada capa nueva sube el coste de despliegue\n\n"
    "## Trade-offs y decisión\n"
    "| Opción | Ventajas | Desventajas | Complejidad |\n"
    "| --- | --- | --- | --- |\n"
    "| Capas [1] | Simple | Acoplamiento | Baja |\n"
    "| Hexagonal [2] | Aislada | Más código | Media |\n"
    "| Microservicios [2] | Escala | Ops | Alta |\n"
    "\n"
    "- Recomendación: Capas [1]\n"
    "- Punto de decisión: arrancar con Capas\n"
)


def caso(citations: list[dict] | None = None) -> dict:
    """Caso minimo valido, con las citations que le pidamos."""
    return {
        "id": "test-001",
        "nombre": "Caso de prueba",
        "project_name": "ProyectoDePrueba",
        "descripcion": "Descripcion de prueba.",
        "citations": citations
        if citations is not None
        else [
            {"pattern_name": "Arquitectura en capas (Layered)", "snippet": "Capas."},
            {"pattern_name": "Microservicios", "snippet": "Servicios."},
        ],
    }


def _con_cuerpo(
    componentes: str, patrones: str = "- Patron A [1]", fuentes: int = 2
) -> str:
    """Salida valida segun produccion para un caso con ``fuentes`` citations,
    con las secciones de componentes y patrones que se pidan.

    La tabla de trade-offs cita ``[1]``..``[min(fuentes, 3)]`` en filas
    distintas, como exige ``_missing_sections(..., source_count=fuentes)``; las
    filas sin fuente van como "Sin fuente RAG", que es lo que pide el prompt.
    """
    filas = [("Capas", "Simple", "Acoplamiento", "Baja"),
             ("Hexagonal", "Aislada", "Más código", "Media"),
             ("Microservicios", "Escala", "Ops", "Alta")]
    tabla = "".join(
        f"| {opcion} {f'[{i}]' if i <= fuentes else '(Sin fuente RAG)'} "
        f"| {ventaja} | {desventaja} | {complejidad} |\n"
        for i, (opcion, ventaja, desventaja, complejidad) in enumerate(filas, 1)
    )
    return (
        f"## Componentes\n{componentes}\n\n"
        "## Tecnologías\n- Python\n\n"
        f"## Patrones\n{patrones}\n\n"
        "## Justificación del patrón principal\n"
        "- El dominio cambia seguido, así que la lógica queda aislada\n"
        "- Riesgo: cada capa nueva sube el coste de despliegue\n\n"
        "## Trade-offs y decisión\n"
        "| Opción | Ventajas | Desventajas | Complejidad |\n"
        "| --- | --- | --- | --- |\n"
        f"{tabla}"
        "\n"
        "- Recomendación: Capas\n"
        "- Punto de decision: arrancar con Capas\n"
    )


# --- Secciones obligatorias -------------------------------------------------


def test_secciones_obligatorias_presentes():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["secciones_ok"] is True


def test_falta_una_seccion_obligatoria_es_fallo():
    sin_patrones = SALIDA_PERFECTA.replace(
        "## Patrones\n- Arquitectura en capas (Layered) [1]\n", ""
    )
    score = score_output(sin_patrones, caso())
    assert score["secciones_ok"] is False
    assert score["pass_estructural"] is False


def test_sin_ninguna_seccion_es_fallo():
    texto = "Es un proyecto chiquito, no hace falta arquitectura."
    score = score_output(texto, caso())
    assert score["secciones_ok"] is False


def test_tecnologias_sin_tilde_cumple_el_contrato():
    """Produccion normaliza acentos: responder 'Tecnologias' sin tilde es valido.

    El scorer exigia la tilde y media como fallida toda propuesta valida de
    produccion (review de #108, lau2413).
    """
    sin_tilde = SALIDA_PERFECTA.replace("## Tecnologías", "## Tecnologias")
    assert sin_tilde != SALIDA_PERFECTA
    score = score_output(sin_tilde, caso())
    assert score["secciones_ok"] is True
    assert score["sin_secciones_extra"] is True
    assert score["pass_estructural"] is True


def test_secciones_requeridas_son_las_del_prompt_real():
    """El contrato es el de produccion (5 secciones), no una copia del harness."""
    assert SECCIONES_REQUERIDAS == (
        "Componentes",
        "Tecnologias",
        "Patrones",
        "Justificación del patrón principal",
        "Trade-offs y decisión",
    )


# --- Orden, extras, preambulo y cierre ---------------------------------------


def test_con_cuerpo_es_valida_segun_produccion():
    """La fixture dice ser una salida valida: lo confirma el validador real."""
    from app.core.proposal_generator import _missing_sections

    for fuentes in (0, 1, 2, 3, 5):
        assert _missing_sections(_con_cuerpo("- API", fuentes=fuentes), fuentes) == []
    assert _missing_sections(SALIDA_PERFECTA, 2) == []


def _hex_con_tabla(filas: str) -> str:
    """Salida para hex-001 (4 citations) con la tabla de trade-offs dada."""
    return (
        "## Componentes\n- API de pedidos [1]\n\n"
        "## Tecnologias\n- Python\n\n"
        "## Patrones\n- Hexagonal [1]\n\n"
        "## Justificación del patrón principal\n"
        "- Aisla el dominio [1]\n- Riesgo: mas codigo de adaptadores\n\n"
        "## Trade-offs y decisión\n"
        "| Opción | Ventajas | Desventajas | Complejidad |\n"
        "| --- | --- | --- | --- |\n"
        f"{filas}\n"
        "- Recomendación: Hexagonal [1]\n"
        "- Punto de decisión: arrancar con Hexagonal\n"
    )


@pytest.mark.parametrize(
    ("filas", "valida"),
    [
        (
            "| Hexagonal [1] | Aislada | Mas codigo | Media |\n"
            "| Capas [2] | Simple | Acoplamiento | Baja |\n"
            "| Microservicios [3] | Escala | Ops | Alta |\n",
            True,
        ),
        (
            "| Hexagonal | Aislada | Mas codigo | Media |\n"
            "| Capas | Simple | Acoplamiento | Baja |\n"
            "| Microservicios | Escala | Ops | Alta |\n",
            False,
        ),
        (
            "| Hexagonal [1] | Aislada | Mas codigo | Media |\n"
            "| Capas [1] | Simple | Acoplamiento | Baja |\n"
            "| Microservicios [1] | Escala | Ops | Alta |\n",
            False,
        ),
    ],
    ids=["cita-1-2-3", "sin-citas", "todas-cita-1"],
)
def test_scorer_aplica_la_regla_de_fuentes_de_la_tabla(filas, valida):
    """Re-review de #108: con ``source_count=0`` el scorer aprobaba tablas que
    produccion rechaza. Ahora el veredicto coincide con el de produccion,
    llamado con los mismos argumentos que ``generate_stream``."""
    from app.core.proposal_generator import _missing_sections

    hex_001 = next(c for c in cargar_casos() if c["id"] == "hex-001")
    salida = _hex_con_tabla(filas)
    produccion = _missing_sections(salida, source_count=len(hex_001["citations"]))
    score = score_output(salida, hex_001)
    assert (produccion == []) is valida
    assert score["secciones_ok"] is valida
    assert score["pass_estructural"] is valida
    assert score["secciones_faltantes"] == produccion


def test_secciones_en_otro_nivel_de_encabezado_no_lanzan():
    """Produccion acepta las secciones en cualquier nivel (``#{1,6}``). El
    scorer indexaba solo los ``##`` y lanzaba KeyError con ``### Componentes``."""
    from app.core.proposal_generator import _missing_sections

    una_h3 = SALIDA_PERFECTA.replace("## Componentes", "### Componentes")
    score = score_output(una_h3, caso())
    assert _missing_sections(una_h3, 2) == []
    assert score["secciones_ok"] is True
    assert score["orden_ok"] is True
    assert score["sin_preambulo"] is True
    assert score["bullets_por_seccion"]["Componentes"] == 2

    todas_h3 = SALIDA_PERFECTA.replace("## ", "### ")
    score = score_output(todas_h3, caso())
    assert score["pass_estructural"] is True
    assert score["bullets_por_seccion"]["Tecnologias"] == 2


def test_seccion_solo_dentro_de_un_bloque_de_codigo_no_lanza():
    """Produccion no ignora el codigo y da la seccion por presente; el scorer
    no le encuentra posicion real: orden False, sin KeyError."""
    en_codigo = SALIDA_PERFECTA.replace(
        "## Componentes\n", "```markdown\n## Componentes\n```\n"
    )
    score = score_output(en_codigo, caso())
    assert score["secciones_ok"] is True
    assert score["orden_ok"] is False
    assert score["bullets_por_seccion"]["Componentes"] == 0
    assert score["pass_estructural"] is False


def test_finish_reason_length_no_pasa_aunque_esten_las_secciones():
    """Produccion descarta una propuesta cortada por limite de tokens."""
    score = score_output(SALIDA_PERFECTA, caso(), finish_reason="length")
    assert score["secciones_ok"] is True
    assert score["sin_corte"] is False
    assert score["pass_estructural"] is False
    assert score_output(SALIDA_PERFECTA, caso(), finish_reason="stop")["sin_corte"]


def test_orden_correcto_de_las_cinco_secciones():
    assert score_output(SALIDA_PERFECTA, caso())["orden_ok"] is True


def test_orden_incorrecto_es_fallo():
    """Las mismas secciones, en otro orden: el contrato de produccion se
    cumple pero el orden no.

    Se intercambian las dos PRIMERAS secciones (Componentes y Tecnologias).
    No vale cualquier reordenamiento: produccion busca el encabezado de
    trade-offs DESPUES del de la justificacion (``_tradeoff_heading``, para no
    confundirlo con un subtitulo "Opciones"/"Alternativas" de otra seccion),
    asi que mover los trade-offs delante de la justificacion los reporta como
    seccion FALTANTE y ``secciones_ok`` ya no aisla el orden. Ese caso se
    cubre aparte, en el test de abajo.
    """
    valida = _con_cuerpo("- Componente [1]", "- Patron A [1]")
    cuerpos = [
        s.replace("## ", "", 1) if s.startswith("## ") else s
        for s in valida.split("\n## ")
    ]
    desordenado = "## " + "\n## ".join([cuerpos[1], cuerpos[0]] + cuerpos[2:])

    score = score_output(desordenado, caso())
    assert score["secciones_ok"] is True
    assert score["orden_ok"] is False
    assert score["pass_estructural"] is False


def test_tradeoffs_antes_de_la_justificacion_cuenta_como_seccion_faltante():
    """Los trade-offs delante de la justificacion: produccion no los reconoce.

    ``_tradeoff_heading`` solo acepta el encabezado de trade-offs despues del
    de la justificacion. Puesto antes, produccion lo da por ausente, asi que
    el scorer (que delega en ``_missing_sections``) reporta la seccion como
    faltante, no solo como desordenada. De cualquier forma no pasa.
    """
    valida = _con_cuerpo("- Componente [1]", "- Patron A [1]")
    cuerpos = [
        s.replace("## ", "", 1) if s.startswith("## ") else s
        for s in valida.split("\n## ")
    ]
    tradeoffs_primero = "## " + "\n## ".join(cuerpos[4:] + cuerpos[:4])

    score = score_output(tradeoffs_primero, caso())
    assert score["secciones_ok"] is False
    assert "Trade-offs y decisión" in score["secciones_faltantes"]
    assert score["pass_estructural"] is False


def test_seccion_extra_detectada():
    con_extra = SALIDA_PERFECTA + "\n## Riesgos\n- Riesgo de proveedor\n"
    score = score_output(con_extra, caso())
    assert score["sin_secciones_extra"] is False
    assert "Riesgos" in score["secciones_extra"]
    assert score["pass_estructural"] is False


def test_sin_secciones_extra_en_salida_correcta():
    assert score_output(SALIDA_PERFECTA, caso())["sin_secciones_extra"] is True


def test_preambulo_es_fallo():
    score = score_output("Claro, aca va la propuesta:\n\n" + SALIDA_PERFECTA, caso())
    assert score["sin_preambulo"] is False
    assert score["pass_estructural"] is False


def test_h1_es_preambulo_y_seccion_extra():
    score = score_output("# Propuesta\n\n" + SALIDA_PERFECTA, caso())
    assert score["sin_preambulo"] is False
    assert "# Propuesta" in score["secciones_extra"]
    assert score["pass_estructural"] is False


def test_cierre_conversacional_se_reporta_sin_tumbar_el_pass():
    score = score_output(SALIDA_PERFECTA + "\nEspero que te sirva.\n", caso())
    assert score["cierre_suelto"] is True
    assert score["pass_estructural"] is True


def test_salida_perfecta_no_tiene_cierre_suelto():
    assert score_output(SALIDA_PERFECTA, caso())["cierre_suelto"] is False


def test_heading_dentro_de_bloque_de_codigo_no_cuenta():
    texto = _con_cuerpo("- API\n\n```markdown\n## Riesgos\n```")
    score = score_output(texto, caso())
    assert score["sin_secciones_extra"] is True
    assert score["pass_estructural"] is True


def test_salida_vacia():
    score = score_output("", caso())
    assert score["vacio"] is True
    assert score["pass_estructural"] is False


# --- Citas ------------------------------------------------------------------


def test_cita_valida_con_tres_citations():
    tres = caso([{"pattern_name": x, "snippet": x} for x in "ABC"])
    score = score_output(_con_cuerpo("- Componente [3]", "- Patron C [3]", 3), tres)
    assert score["citas_validas"] is True
    assert score["pass_estructural"] is True
    # Componentes, Patrones y las tres filas de la tabla.
    assert score["marcadores"] == [3, 3, 1, 2, 3]


def test_cita_fuera_de_rango_es_invalida():
    score = score_output(_con_cuerpo("- Componente [9]"), caso())
    assert score["citas_validas"] is False
    assert 9 in score["marcadores_fuera_de_rango"]
    assert score["pass_estructural"] is False


def test_caso_sin_citations_con_marcador_es_fallo_esperado():
    """Sin contexto RAG el modelo no deberia inventar referencias [N]."""
    score = score_output(
        _con_cuerpo("- Script cron [1]", "- No aplica", fuentes=0), caso([])
    )
    assert score["citas_validas"] is False
    assert score["pass_estructural"] is False


def test_caso_sin_citations_sin_marcadores_pasa_citas():
    score = score_output(_con_cuerpo("- Script cron", "- No aplica", fuentes=0), caso([]))
    assert score["citas_validas"] is True
    assert score["pass_estructural"] is True


def test_enlace_markdown_no_cuenta_como_cita():
    score = score_output(_con_cuerpo("- API [documentacion](#api)"), caso())
    assert score["citas_validas"] is True
    # Solo Patrones y las dos filas de la tabla con fuente: el enlace no cuenta.
    assert score["marcadores"] == [1, 1, 2]


def test_marcadores_ignora_texto_no_numerico():
    assert marcadores_cita("ver [Anexo 1] y [Componentes]") == []


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("[1, 2]", [1, 2]),
        ("[1,3]", [1, 3]),
        ("[1-3]", [1, 2, 3]),
        ("[1–3]", [1, 2, 3]),
        ("[1, 3-4]", [1, 3, 4]),
        ("[2][5]", [2, 5]),
        ("[1-999]", [1, 999]),
    ],
)
def test_marcadores_lista_y_rango(texto, esperado):
    assert marcadores_cita(texto) == esperado


def test_rango_que_se_pasa_de_las_citations_es_invalido():
    una = caso([{"pattern_name": "A", "snippet": "a"}])
    score = score_output(_con_cuerpo("- Componente [1-3]", fuentes=1), una)
    assert score["citas_validas"] is False
    assert score["marcadores_fuera_de_rango"] == [2, 3]


def test_indice_en_bloque_de_codigo_no_es_cita():
    texto = _con_cuerpo(
        "- Script\n\n```python\nprimero = arr[0]\n```", "- No aplica", fuentes=0
    )
    score = score_output(texto, caso([]))
    assert score["marcadores"] == []
    assert score["citas_validas"] is True


def test_indice_en_codigo_inline_no_es_cita():
    assert marcadores_cita("usar `arr[0]` y luego [1]") == [1]


# --- Metricas secundarias ---------------------------------------------------


def test_bullets_por_seccion_se_cuentan_por_seccion():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["bullets_por_seccion"] == {
        "Componentes": 2,
        "Tecnologias": 2,
        "Patrones": 1,
        "Justificación del patrón principal": 2,
        "Trade-offs y decisión": 2,
    }


def test_bullets_numerados_y_con_punto_medio():
    texto = _con_cuerpo("1. API\n2) Worker\n• Cola\n+ Cache")
    assert score_output(texto, caso())["bullets_por_seccion"]["Componentes"] == 4


def test_largo_es_la_cantidad_de_caracteres():
    assert score_output(SALIDA_PERFECTA, caso())["largo"] == len(SALIDA_PERFECTA)


def test_pass_estructural_true():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["pass_estructural"] is True
    for clave in ("secciones_ok", "orden_ok", "sin_secciones_extra", "sin_preambulo",
                  "citas_validas", "sin_corte"):
        assert score[clave] is True


# --- Agregacion de variabilidad --------------------------------------------


def _ejecucion(caso_id: str, modelo: str, repeat: int, markdown: str) -> dict:
    return {
        "caso_id": caso_id,
        "modelo": modelo,
        "repeat": repeat,
        "ok": True,
        "markdown": markdown,
        "score": score_output(markdown, caso()),
    }


def _fallida(caso_id: str, modelo: str, repeat: int) -> dict:
    return {"caso_id": caso_id, "modelo": modelo, "repeat": repeat, "ok": False,
            "error": "429"}


def test_variabilidad_detecta_repeats_identicos():
    ejecuciones = [_ejecucion("c1", "m1", i, SALIDA_PERFECTA) for i in (1, 2, 3)]
    v = calcular_variabilidad(ejecuciones, "c1", "m1")
    assert v["tasa_exacta"] == 1.0
    assert v["acuerdo_estructural"] == 1.0
    assert v["desvio_largo"] == 0.0
    assert v["salidas_distintas"] == 1
    assert v["similitud_media"] == 1.0
    assert v["pares"] == 3


def test_variabilidad_detecta_repeats_distintos():
    a = _con_cuerpo("- API [1]")
    b = a + "\n- Nota adicional\n"
    c = a.replace("- Python", "- Python 3.12")
    ejecuciones = [_ejecucion("c1", "m1", i, t) for i, t in enumerate((a, b, c), 1)]
    v = calcular_variabilidad(ejecuciones, "c1", "m1")
    assert v["tasa_exacta"] == 0.0
    assert v["acuerdo_estructural"] == 1.0
    assert v["desvio_largo"] > 0
    assert v["salidas_distintas"] == 3
    assert 0.8 < v["similitud_media"] < 1.0


def test_exacta_normalizada_ignora_espacios_sobrantes():
    a = SALIDA_PERFECTA
    b = SALIDA_PERFECTA.replace("- Python\n", "- Python   \n").replace("\n\n", "\n\n\n")
    v = calcular_variabilidad(
        [_ejecucion("c1", "m1", 1, a), _ejecucion("c1", "m1", 2, b)], "c1", "m1"
    )
    assert v["tasa_exacta"] == 0.0
    assert v["tasa_exacta_normalizada"] == 1.0


def test_variabilidad_con_un_solo_exito_no_inventa_estabilidad():
    v = calcular_variabilidad(
        [_fallida("c1", "m1", 1), _ejecucion("c1", "m1", 2, SALIDA_PERFECTA)], "c1", "m1"
    )
    assert v["repeats_ok"] == 1
    assert v["repeats_fallidos"] == 1
    assert v["tasa_exacta"] is None
    assert v["desvio_largo"] is None
    assert v["tasa_pass_estructural"] == 1.0


def test_variabilidad_sin_exitos_tiene_todas_las_claves_en_none():
    v = calcular_variabilidad([_fallida("c1", "m1", 1)], "c1", "m1")
    for clave in ("tasa_pass_estructural", "largo_medio", "desvio_largo", "tasa_exacta",
                  "similitud_media", "acuerdo_estructural", "solapamiento_citas"):
        assert v[clave] is None, clave


def test_jaccard_de_conjuntos_vacios():
    assert _jaccard(set(), set()) == 1.0
    assert _jaccard({1}, set()) == 0.0
    assert _jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)


def test_resumen_no_promedia_casos_sin_datos():
    """Un caso con desvio 19 y dos sin datos debe dar 19, no 6.33."""
    corto = SALIDA_PERFECTA
    largo = SALIDA_PERFECTA + "x" * 38
    ejecuciones = [
        _ejecucion("c1", "m1", 1, corto),
        _ejecucion("c1", "m1", 2, largo),
        _fallida("c2", "m1", 1),
        _fallida("c2", "m1", 2),
        _fallida("c3", "m1", 1),
        _ejecucion("c3", "m1", 2, corto),
    ]
    variabilidad = [calcular_variabilidad(ejecuciones, c, "m1") for c in ("c1", "c2", "c3")]
    resumen = resumir_por_modelo(variabilidad, ejecuciones)["m1"]
    assert resumen["desvio_largo"] == pytest.approx(19.0)
    assert resumen["casos_medibles"] == 1
    assert resumen["ejecuciones"] == 6
    assert resumen["ejecuciones_ok"] == 3
    assert resumen["ejecuciones_fallidas"] == 3


def test_resumen_distingue_pasa_siempre_de_falla_siempre():
    malo = "Sin formato."
    ejecuciones = [
        _ejecucion("bien", "m1", 1, SALIDA_PERFECTA),
        _ejecucion("bien", "m1", 2, SALIDA_PERFECTA),
        _ejecucion("mal", "m1", 1, malo),
        _ejecucion("mal", "m1", 2, malo),
    ]
    variabilidad = [calcular_variabilidad(ejecuciones, c, "m1") for c in ("bien", "mal")]
    resumen = resumir_por_modelo(variabilidad, ejecuciones)["m1"]
    assert resumen["acuerdo_estructural"] == 1.0
    assert resumen["casos_pass_siempre"] == 1
    assert resumen["casos_falla_siempre"] == 1
    assert resumen["tasa_pass_estructural"] == 0.5


# --- Filtro de peores -------------------------------------------------------


def test_filtrar_peores_separa_peores_insuficientes_y_fallidos():
    """``None or 1.0`` excluia los pares sin datos; y un par con un solo exito
    no es "todos fallidos". Las tres listas son disjuntas."""
    variabilidad = [
        {"caso_id": "c1", "modelo": "m1", "tasa_exacta": 0.5, "repeats_ok": 3},
        {"caso_id": "c2", "modelo": "m1", "tasa_exacta": 1.0, "repeats_ok": 3},
        {"caso_id": "c3", "modelo": "m1", "tasa_exacta": None, "repeats_ok": 0},
        {"caso_id": "c4", "modelo": "m2", "tasa_exacta": None, "repeats_ok": 1},
        {"caso_id": "c5", "modelo": "m1", "tasa_exacta": 0.0, "repeats_ok": 2},
    ]
    resultado = _filtrar_peores(variabilidad)
    assert {v["caso_id"] for v in resultado["peor"]} == {"c1", "c5"}
    assert {v["caso_id"] for v in resultado["insuficientes"]} == {"c4"}
    assert {v["caso_id"] for v in resultado["all_failed"]} == {"c3"}


def test_filtrar_peores_con_lista_vacia():
    assert _filtrar_peores([]) == {"peor": [], "insuficientes": [], "all_failed": []}


# --- Helpers del runner -----------------------------------------------------


def test_contenido_normaliza_str_lista_y_none():
    assert _contenido(AIMessageChunk(content="hola")) == "hola"
    assert _contenido(MagicMock(content=["a", {"text": "b"}, {"type": "x"}])) == "ab"
    assert _contenido(MagicMock(content=None)) == ""
    assert _contenido("plano") == "plano"


def test_es_rate_limit():
    assert _es_rate_limit(RuntimeError("Error code: 429 - rate limit"))
    assert _es_rate_limit(RuntimeError("Too Many Requests"))
    error = RuntimeError("boom")
    error.status_code = 429  # type: ignore[attr-defined]
    assert _es_rate_limit(error)
    assert not _es_rate_limit(RuntimeError("500 internal error"))


def test_resolver_proveedor_usa_groq_api_key_con_el_endpoint_default():
    from app.core.llm_loader import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL

    base_url, api_key, modelo = resolver_proveedor({"GROQ_API_KEY": "gsk-fake"})
    assert base_url == DEFAULT_LLM_BASE_URL
    assert api_key == "gsk-fake"
    assert modelo == DEFAULT_LLM_MODEL


def test_resolver_proveedor_no_manda_la_clave_de_groq_a_otro_endpoint():
    _, api_key, _ = resolver_proveedor(
        {"GROQ_API_KEY": "gsk-fake", "LLM_BASE_URL": "https://otro.example/v1"}
    )
    assert api_key == ""


def test_resolver_proveedor_prefiere_llm_api_key():
    _, api_key, modelo = resolver_proveedor(
        {"GROQ_API_KEY": "gsk-fake", "LLM_API_KEY": "sk-otra", "LLM_MODEL": "m"}
    )
    assert api_key == "sk-otra"
    assert modelo == "m"


# --- Carga de casos ---------------------------------------------------------


def _yaml(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "cases.yaml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


_CASO_YAML = """
casos:
  - id: a-001
    nombre: "A"
    project_name: "P"
    descripcion: "D"
"""


def test_caso_sin_clave_citations_es_lista_vacia(tmp_path):
    assert cargar_casos(_yaml(tmp_path, _CASO_YAML))[0]["citations"] == []


def test_caso_con_citations_null_es_lista_vacia(tmp_path):
    casos = cargar_casos(_yaml(tmp_path, _CASO_YAML + "    citations: null\n"))
    assert casos[0]["citations"] == []


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        ("otra: 1\n", "clave 'casos'"),
        ("casos: []\n", "ningun caso"),
        (_CASO_YAML + "    citations: {}\n", "debe ser una lista"),
        (_CASO_YAML + "    citations:\n      - pattern_name: X\n", "no tiene 'snippet'"),
        (_CASO_YAML + "    citations:\n      - texto\n", "no es un mapping"),
        (_CASO_YAML + "    feedback: ''\n", "'feedback'"),
        (_CASO_YAML.replace('descripcion: "D"', 'descripcion: ""'), "'descripcion'"),
        (_CASO_YAML + _CASO_YAML.split("casos:\n")[1], "id duplicado"),
    ],
)
def test_cargar_casos_rechaza_schema_invalido(tmp_path, contenido, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        cargar_casos(_yaml(tmp_path, contenido))


# --- Corpus -----------------------------------------------------------------


def test_el_corpus_real_carga_y_es_valido():
    casos = cargar_casos()
    assert len(casos) >= 8
    assert sum(1 for c in casos if not c["citations"]) >= 2
    assert any(len(c["citations"]) >= 4 for c in casos)
    # Produccion recupera k=5: nunca mas de 5 citations por caso.
    assert all(len(c["citations"]) <= 5 for c in casos)
    # Produccion puede devolver varios chunks del mismo patron.
    assert any(
        len({x["pattern_name"] for x in c["citations"]}) < len(c["citations"])
        for c in casos
    )
    # El camino de iteracion esta cubierto.
    assert any(c.get("feedback") and c.get("prior_content") for c in casos)


def _chunks_de_produccion() -> dict[str, set[str]]:
    """``pattern_name -> {chunk_text}`` con el chunker real del seed.

    Se ejecuta ``seed_pattern_chunks`` contra un cursor falso y sin modelo de
    embeddings: lo unico que interesa es el texto que insertaria.
    """
    raiz = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(raiz / "scripts"))
    try:
        import seed_patterns
    finally:
        sys.path.pop(0)

    chunks: dict[str, set[str]] = {}
    cursor = MagicMock()
    with patch.object(seed_patterns, "embed_passage", return_value=[0.0]):
        for patron in seed_patterns.load_patterns():
            cursor.reset_mock()
            seed_patterns.seed_pattern_chunks(cursor, 1, patron)
            textos = {
                llamada.args[1][2]
                for llamada in cursor.execute.call_args_list
                if "INSERT" in llamada.args[0]
            }
            chunks[patron["pattern_name"]] = textos
    return chunks


def test_cada_snippet_es_un_chunk_real_truncado_como_en_produccion():
    """Lo que el corpus le muestra al modelo es lo que produccion le mostraria."""
    chunks = _chunks_de_produccion()
    errores = []
    for c in cargar_casos():
        for i, cita in enumerate(c["citations"], start=1):
            nombre = cita["pattern_name"]
            if nombre not in chunks:
                errores.append(f"{c['id']} cita {i}: patron inexistente '{nombre}'")
            elif cita["snippet"] not in {t[:240] for t in chunks[nombre]}:
                errores.append(
                    f"{c['id']} cita {i}: el snippet no es chunk_text[:240] de "
                    f"'{nombre}' (¿se edito data/patterns/?)"
                )
    assert not errores, "\n".join(errores)


def test_los_casos_reales_sin_citations_rechazan_la_salida_de_ejemplo():
    for caso_real in cargar_casos():
        if not caso_real["citations"]:
            assert score_output(SALIDA_PERFECTA, caso_real)["citas_validas"] is False


# --- El prompt real se construye para CADA caso (B1) -----------------------


def test_el_prompt_real_se_construye_para_cada_caso_del_corpus():
    """Gate contra el B1: cada caso arma su prompt con la funcion de produccion,
    no vacio, con el project_name, la descripcion, las cinco secciones y, si
    hay iteracion, el feedback y la propuesta previa."""
    from evals.runner import armar_prompt

    for c in cargar_casos():
        prompt = armar_prompt(c)
        assert prompt and c["project_name"] in prompt, c["id"]
        # La descripcion entra al prompt como en produccion (#112).
        assert c["descripcion"].strip() in prompt, c["id"]
        for seccion in SECCIONES_REQUERIDAS:
            assert f"## {seccion}" in prompt, (c["id"], seccion)
        if c.get("feedback"):
            assert c["feedback"].strip() in prompt, c["id"]
        if c.get("prior_content"):
            assert c["prior_content"][:200] in prompt, c["id"]


def test_dry_run_devuelve_no_cero_si_build_prompt_falla():
    with patch(
        "app.core.proposal_generator._build_prompt",
        side_effect=RuntimeError("exploto el prompt"),
    ):
        assert dry_run(cargar_casos()) == 1


def test_dry_run_valida_todos_los_casos_no_solo_el_primero():
    from app.core.proposal_generator import _build_prompt as real

    casos = cargar_casos()
    # El ultimo caso (iter-001) comparte project_name con mono-002: se lo
    # identifica por su feedback, que es unico.
    ultimo = casos[-1]
    assert ultimo["feedback"]
    llamados: list[str] = []

    # ``**kwargs`` reenvia description/requirements_text/documents_text: con
    # una firma fija, los 11 casos fallaban con TypeError y el test pasaba sin
    # ejecutar este cuerpo (re-review de #108).
    def falla_en_el_ultimo(citations, prior, feedback, project_name, **kwargs):
        llamados.append(project_name)
        if feedback == ultimo["feedback"]:
            raise RuntimeError("solo el ultimo")
        return real(citations, prior, feedback, project_name, **kwargs)

    with patch("app.core.proposal_generator._build_prompt", side_effect=falla_en_el_ultimo):
        assert dry_run(casos) == 1
    # Se armaron todos los casos y solo el ultimo fallo: el resto paso por la
    # funcion real.
    assert llamados == [c["project_name"] for c in casos]
    assert sum(1 for c in casos if c.get("feedback") == ultimo["feedback"]) == 1


def test_dry_run_ok_con_el_corpus_real():
    assert dry_run(cargar_casos()) == 0


# --- Construccion del modelo ------------------------------------------------


def test_construir_modelo_omite_temperature_para_serie_o():
    """Igual que produccion: la serie o* solo admite 1 y responde 400 a otro valor."""
    with patch("langchain.chat_models.init_chat_model") as mock_init:
        construir_modelo("o1-mini", "https://api.openai.com/v1", "sk-test", 0.0)
    assert "temperature" not in mock_init.call_args.kwargs


def test_construir_modelo_manda_temperature_para_familia_comun():
    with patch("langchain.chat_models.init_chat_model") as mock_init:
        construir_modelo("gpt-4o-mini", "https://api.openai.com/v1", "sk-test", 0.0)
    kwargs = mock_init.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["model_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["api_key"] == "sk-test"


# --- Corrida completa con un chat falso -------------------------------------


class ChatFalso:
    """Imita ``BaseChatModel.stream``: cada respuesta es una lista de chunks o
    una excepcion. Las respuestas se consumen en orden y la ultima se repite."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.prompts: list[str] = []
        self.kwargs: list[dict] = []

    def stream(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.kwargs.append(kwargs)
        respuesta = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(respuesta, Exception):
            raise respuesta
        return iter(respuesta)


def chunks(texto: str, finish_reason: str = "stop") -> list[AIMessageChunk]:
    mitad = len(texto) // 2
    return [
        AIMessageChunk(content=texto[:mitad]),
        AIMessageChunk(
            content=texto[mitad:],
            response_metadata={"finish_reason": finish_reason},
            usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        ),
    ]


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    """API key falsa, sin espera real y resultados en tmp_path."""
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "GROQ_API_KEY",
                "LLM_TEMPERATURE", "LLM_MODELS_WITHOUT_TEMPERATURE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-fake")
    monkeypatch.setattr("evals.runner.time.sleep", lambda _s: None)
    return tmp_path


def correr(tmp_path: Path, chats: dict, *argv: str) -> tuple[int, dict | None]:
    def construir(modelo, *_args):
        chat = chats[modelo]
        if isinstance(chat, Exception):
            raise chat
        return chat

    with patch("evals.runner.construir_modelo", side_effect=construir):
        codigo = main(["--sleep", "0", "--output-dir", str(tmp_path), *argv])
    archivos = sorted(tmp_path.glob("*.json"))
    datos = json.loads(archivos[-1].read_text(encoding="utf-8")) if archivos else None
    return codigo, datos


def test_corrida_exitosa_sale_con_cero_y_guarda_procedencia(entorno):
    chat = ChatFalso(chunks(_con_cuerpo("- API", "- No aplica", fuentes=0)))
    codigo, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "vacio-001", "--repeats", "2"
    )
    assert codigo == 0
    assert datos["gate"] == {"paso": True, "motivos": []}
    meta = datos["metadata"]
    assert meta["temperature_efectiva"] == {"m1": 0.0}
    assert meta["temperature_origen"] == "DEFAULT_LLM_TEMPERATURE"
    procedencia = meta["procedencia"]
    assert len(procedencia["cases_yaml_sha256"]) == 64
    assert len(procedencia["build_prompt_fuente_sha256"]) == 64
    assert set(procedencia["prompts_sha256"]) == {"vacio-001"}
    assert "langchain-core" in procedencia["paquetes"]
    ejecucion = datos["ejecuciones"][0]
    assert ejecucion["finish_reason"] == "stop"
    assert ejecucion["usage"]["output_tokens"] == 20
    assert ejecucion["markdown"] == _con_cuerpo("- API", "- No aplica", fuentes=0)
    assert ejecucion["score"]["pass_estructural"] is True
    assert chat.kwargs[0] == {"stream_usage": True}
    assert datos["variabilidad"][0]["tasa_exacta"] == 1.0


def test_temperatura_efectiva_de_la_serie_o_es_none(entorno):
    chat = ChatFalso(chunks(SALIDA_PERFECTA))
    _, datos = correr(
        entorno, {"o3-mini": chat}, "--models", "o3-mini", "--case", "hex-001",
        "--repeats", "2",
    )
    assert datos["metadata"]["temperature_solicitada"] == 0.0
    assert datos["metadata"]["temperature_efectiva"] == {"o3-mini": None}


def test_orden_intercalado_por_repeat(entorno):
    chat = ChatFalso(chunks(SALIDA_PERFECTA))
    _, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--case",
        "mono-001", "--repeats", "2",
    )
    orden = [(e["repeat"], e["caso_id"]) for e in datos["ejecuciones"]]
    assert orden == [(1, "hex-001"), (1, "mono-001"), (2, "hex-001"), (2, "mono-001")]


def test_todas_las_invocaciones_fallidas_sale_con_uno(entorno):
    chat = ChatFalso(RuntimeError("500 internal"))
    codigo, datos = correr(entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001")
    assert codigo == 1
    assert "ninguna invocacion fue exitosa" in datos["gate"]["motivos"]


def test_ningun_modelo_construible_sale_con_uno(entorno):
    """Antes: ``ejecuciones`` vacia -> exit 0 sin medir nada."""
    codigo, datos = correr(
        entorno, {"m1": RuntimeError("no existe")}, "--models", "m1", "--case", "hex-001"
    )
    assert codigo == 1
    assert datos["ejecuciones"] == []
    assert datos["errores_construccion"][0]["modelo"] == "m1"
    assert datos["resumen_por_modelo"]["m1"]["error_construccion"]


def test_un_modelo_no_construible_entre_varios_sale_con_uno_y_queda_registrado(entorno):
    chats = {"a": ChatFalso(chunks(SALIDA_PERFECTA)), "b": RuntimeError("404 model")}
    codigo, datos = correr(entorno, chats, "--models", "a,b", "--case", "hex-001")
    assert codigo == 1
    assert [e["modelo"] for e in datos["errores_construccion"]] == ["b"]
    assert any("no se pudo construir: b" in m for m in datos["gate"]["motivos"])
    assert "b" in datos["resumen_por_modelo"]


def test_salida_vacia_cuenta_como_fallo(entorno):
    """Tres vacias daban exacta = acuerdo = citas = 1.0: 'reproducibilidad perfecta'."""
    chat = ChatFalso(chunks("", finish_reason="length"))
    codigo, datos = correr(entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001")
    assert codigo == 1
    ejecucion = datos["ejecuciones"][0]
    assert ejecucion["ok"] is False
    assert ejecucion["finish_reason"] == "length"
    assert "vacio" in ejecucion["error"]
    assert datos["variabilidad"][0]["tasa_exacta"] is None


def test_tasa_de_exito_bajo_el_minimo_sale_con_uno(entorno):
    """1 fallo de 6 es 83%: por debajo del 90% por defecto."""
    chat = ChatFalso(
        RuntimeError("timeout"), *[chunks(SALIDA_PERFECTA)] * 5
    )
    codigo, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--repeats", "6"
    )
    assert codigo == 1
    assert any("min-ok-rate" in m for m in datos["gate"]["motivos"])

    chat = ChatFalso(RuntimeError("timeout"), *[chunks(SALIDA_PERFECTA)] * 5)
    codigo, _ = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--repeats", "6",
        "--min-ok-rate", "0.8",
    )
    assert codigo == 0


def test_rate_limit_se_reintenta(entorno):
    chat = ChatFalso(RuntimeError("Error code: 429"), chunks(SALIDA_PERFECTA))
    codigo, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--repeats", "2"
    )
    assert codigo == 0
    assert datos["ejecuciones"][0]["intentos"] == 2
    assert all(e["ok"] for e in datos["ejecuciones"])


def test_rate_limit_agota_reintentos(entorno):
    chat = ChatFalso(RuntimeError("Error code: 429"))
    codigo, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--retries", "1"
    )
    assert codigo == 1
    assert datos["ejecuciones"][0]["intentos"] == 2


def test_case_inexistente_sale_con_dos_y_mensaje(entorno, capsys):
    codigo, datos = correr(entorno, {}, "--case", "nope")
    assert codigo == 2
    assert datos is None
    assert "--case desconocido: nope" in capsys.readouterr().err


def test_sin_api_key_sale_con_dos(entorno, monkeypatch, capsys):
    monkeypatch.delenv("GROQ_API_KEY")
    codigo, _ = correr(entorno, {}, "--case", "hex-001")
    assert codigo == 2
    assert "LLM_API_KEY" in capsys.readouterr().err


def test_un_solo_repeat_sale_con_dos(entorno):
    codigo, _ = correr(entorno, {}, "--repeats", "1")
    assert codigo == 2


def test_min_ok_rate_fuera_de_rango_es_error_de_uso():
    with pytest.raises(SystemExit) as exc:
        main(["--min-ok-rate", "1.5"])
    assert exc.value.code == 2


def test_un_encabezado_no_h2_no_aborta_la_corrida(entorno):
    """Re-review de #108: con ``### Componentes`` el scorer lanzaba KeyError, la
    excepcion subia hasta ``main`` y no se escribia ningun JSON."""
    buena = _con_cuerpo("- API", "- No aplica", fuentes=0)
    rara = buena.replace("## Componentes", "### Componentes")
    chat = ChatFalso(*[chunks(buena)] * 3, chunks(rara))
    codigo, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "vacio-001", "--repeats", "4"
    )
    assert codigo == 0
    assert datos is not None
    assert len(datos["ejecuciones"]) == 4
    assert all(e["ok"] for e in datos["ejecuciones"])


def test_un_error_del_scorer_no_aborta_la_corrida(entorno):
    """Si el scorer lanza, la ejecucion queda fallida con su markdown y la
    corrida sigue y escribe el JSON."""
    from evals import runner

    real = runner.score_output
    llamadas = {"n": 0}

    def score_que_falla_una_vez(*args, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise KeyError("componentes")
        return real(*args, **kwargs)

    chat = ChatFalso(chunks(SALIDA_PERFECTA))
    with patch("evals.runner.score_output", side_effect=score_que_falla_una_vez):
        codigo, datos = correr(
            entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--repeats", "3"
        )
    assert codigo == 1  # 2/3 exitosas: debajo del --min-ok-rate por defecto
    primera = datos["ejecuciones"][0]
    assert primera["ok"] is False
    assert "error del scorer" in primera["error"]
    assert primera["markdown"] == SALIDA_PERFECTA
    assert all(e["ok"] for e in datos["ejecuciones"][1:])


def test_finish_reason_length_llega_al_scorer(entorno):
    chat = ChatFalso(chunks(SALIDA_PERFECTA, finish_reason="length"))
    _, datos = correr(
        entorno, {"m1": chat}, "--models", "m1", "--case", "hex-001", "--repeats", "2"
    )
    score = datos["ejecuciones"][0]["score"]
    assert score["sin_corte"] is False
    assert score["pass_estructural"] is False


# --- Temperatura: misma regla que produccion --------------------------------


def test_temperatura_por_defecto_es_la_de_produccion(monkeypatch):
    from app.core.llm_loader import DEFAULT_LLM_TEMPERATURE
    from evals.runner import resolver_temperatura

    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    assert resolver_temperatura(None) == (DEFAULT_LLM_TEMPERATURE, "DEFAULT_LLM_TEMPERATURE")

    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    assert resolver_temperatura(None) == (0.7, "LLM_TEMPERATURE")

    # Invalida: produccion cae al default, el harness tambien.
    monkeypatch.setenv("LLM_TEMPERATURE", "caliente")
    assert resolver_temperatura(None) == (DEFAULT_LLM_TEMPERATURE, "DEFAULT_LLM_TEMPERATURE")

    assert resolver_temperatura(1.0) == (1.0, "--temperature")


def test_corrida_usa_llm_temperature_si_no_se_pasa_flag(entorno, monkeypatch):
    monkeypatch.setenv("LLM_TEMPERATURE", "0.4")
    construidos: list[float] = []
    chat = ChatFalso(chunks(SALIDA_PERFECTA))

    def construir(modelo, base_url, api_key, temperature):
        construidos.append(temperature)
        return chat

    with patch("evals.runner.construir_modelo", side_effect=construir):
        codigo = main(["--sleep", "0", "--output-dir", str(entorno), "--models", "m1",
                       "--case", "hex-001", "--repeats", "2"])
    assert codigo == 0
    assert construidos == [0.4]
    datos = json.loads(sorted(entorno.glob("*.json"))[-1].read_text(encoding="utf-8"))
    assert datos["metadata"]["temperature_solicitada"] == 0.4
    assert datos["metadata"]["temperature_origen"] == "LLM_TEMPERATURE"
    assert datos["metadata"]["temperature_efectiva"] == {"m1": 0.4}
