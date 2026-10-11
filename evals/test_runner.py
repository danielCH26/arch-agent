"""
Tests del scorer del golden set.

Todo corre offline: no hay red, ni API key, ni base de datos. El scorer es una
funcion pura, asi que estos tests son deterministas y valen como puerta de calidad
en CI.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from evals.runner import (
    SECCIONES_REQUERIDAS,
    _filtrar_peores,
    _jaccard,
    calcular_variabilidad,
    cargar_casos,
    construir_modelo,
    marcadores_cita,
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
    "- Arquitectura en capas (Layered) [1]\n"
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


def test_titulo_con_tilde_en_tecnologias_cumple_el_contrato():
    """El prompt real pide 'Tecnologías' con tilde; el scorer lo acepta tal cual."""
    con_tilde = SALIDA_PERFECTA.replace("## Tecnologias", "## Tecnologías")
    score = score_output(con_tilde, caso())
    assert score["secciones_ok"] is True


# --- Orden ------------------------------------------------------------------


def test_orden_correcto_de_las_tres_secciones():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["orden_ok"] is True


def test_orden_incorrecto_es_fallo():
    desordenado = (
        "## Patrones\n- Arquitectura en capas (Layered) [1]\n\n"
        "## Componentes\n- API de pedidos [1]\n\n"
        "## Tecnologías\n- Python\n"
    )
    score = score_output(desordenado, caso())
    assert score["secciones_ok"] is True
    assert score["orden_ok"] is False
    assert score["pass_estructural"] is False


# --- Secciones extra --------------------------------------------------------


def test_seccion_extra_detectada():
    con_extra = SALIDA_PERFECTA.replace(
        "## Patrones\n- Arquitectura en capas (Layered) [1]\n",
        "## Patrones\n- Arquitectura en capas (Layered) [1]\n\n"
        "## Riesgos\n- Riesgo de proveedor\n",
    )
    score = score_output(con_extra, caso())
    assert score["sin_secciones_extra"] is False
    assert "Riesgos" in score["secciones_extra"]
    assert score["pass_estructural"] is False


def test_sin_secciones_extra_en_salida_correcta():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["sin_secciones_extra"] is True


# --- Citas ------------------------------------------------------------------


def test_cita_valida_con_tres_citations():
    tres = caso(
        [
            {"pattern_name": "A", "snippet": "a"},
            {"pattern_name": "B", "snippet": "b"},
            {"pattern_name": "C", "snippet": "c"},
        ]
    )
    texto = (
        "## Componentes\n- Componente [3]\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patron C [3]\n"
    )
    score = score_output(texto, tres)
    assert score["citas_validas"] is True
    assert score["marcadores"] == [3, 3]


def test_cita_fuera_de_rango_es_invalida():
    texto = (
        "## Componentes\n- Componente [9]\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patron A [1]\n"
    )
    score = score_output(texto, caso())
    assert score["citas_validas"] is False
    assert 9 in score["marcadores_fuera_de_rango"]
    assert score["pass_estructural"] is False


def test_caso_sin_citations_con_marcador_es_fallo_esperado():
    """Sin contexto RAG el modelo no deberia inventar referencias [N]."""
    texto = (
        "## Componentes\n- Script cron [1]\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- No aplica\n"
    )
    score = score_output(texto, caso([]))
    assert score["citas_validas"] is False
    assert score["pass_estructural"] is False


def test_caso_sin_citations_sin_marcadores_pasa_citas():
    texto = (
        "## Componentes\n- Script cron\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- No aplica a este caso\n"
    )
    score = score_output(texto, caso([]))
    assert score["citas_validas"] is True


def test_enlace_markdown_no_cuenta_como_cita():
    texto = (
        "## Componentes\n- API [documentacion](#api)\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patron A [1]\n"
    )
    score = score_output(texto, caso())
    assert score["citas_validas"] is True
    assert score["marcadores"] == [1]


def test_marcadores_ignora_texto_no_numerico():
    assert marcadores_cita("ver [Anexo 1] y [Componentes]") == []


# --- Metricas secundarias ---------------------------------------------------


def test_bullets_por_seccion_se_cuentan_por_seccion():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["bullets_por_seccion"]["Componentes"] == 2
    assert score["bullets_por_seccion"]["Tecnologías"] == 2
    assert score["bullets_por_seccion"]["Patrones"] == 1


def test_largo_es_la_cantidad_de_caracteres():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["largo"] == len(SALIDA_PERFECTA)


def test_pass_estructural_true():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["pass_estructural"] is True
    assert score["secciones_ok"] is True
    assert score["orden_ok"] is True
    assert score["sin_secciones_extra"] is True
    assert score["citas_validas"] is True


def test_secciones_requeridas_son_las_del_prompt_real():
    """Guarda contra cambiar el contrato por accidente desde el harness."""
    assert SECCIONES_REQUERIDAS == ("Componentes", "Tecnologías", "Patrones")


# --- Agregacion de variabilidad --------------------------------------------


def _ejecucion(caso_id: str, modelo: str, repeat: int, markdown: str, score: dict) -> dict:
    return {
        "caso_id": caso_id,
        "modelo": modelo,
        "repeat": repeat,
        "ok": True,
        "markdown": markdown,
        "score": score,
    }


def test_variabilidad_detecta_repeats_identicos():
    ejecuciones = [
        _ejecucion("c1", "m1", i, SALIDA_PERFECTA, score_output(SALIDA_PERFECTA, caso()))
        for i in (1, 2, 3)
    ]
    v = calcular_variabilidad(ejecuciones, "c1", "m1")
    assert v["tasa_exacta"] == 1.0
    assert v["acuerdo_estructural"] == 1.0
    assert v["desvio_largo"] == 0.0


def test_variabilidad_detecta_repeats_distintos():
    base = (
        "## Componentes\n- API [1]\n\n"
        "## Tecnologías\n- Python\n\n"
        "## Patrones\n- Patron A [1]\n"
    )
    a = base
    b = base + "\n- Nota adicional\n"
    c = base.replace("- Python", "- Python 3.12")
    ejecuciones = [
        _ejecucion("c1", "m1", 1, a, score_output(a, caso())),
        _ejecucion("c1", "m1", 2, b, score_output(b, caso())),
        _ejecucion("c1", "m1", 3, c, score_output(c, caso())),
    ]
    v = calcular_variabilidad(ejecuciones, "c1", "m1")
    assert v["tasa_exacta"] == 0.0
    assert v["acuerdo_estructural"] == 1.0
    assert v["desvio_largo"] > 0


def test_variabilidad_ignora_ejecuciones_fallidas():
    v = calcular_variabilidad(
        [
            {"caso_id": "c1", "modelo": "m1", "repeat": 1, "ok": False, "error": "429"},
            _ejecucion(
                "c1", "m1", 2, SALIDA_PERFECTA, score_output(SALIDA_PERFECTA, caso())
            ),
        ],
        "c1",
        "m1",
    )
    assert v["repeats_ok"] == 1
    assert v["repeats_fallidos"] == 1
    assert v["tasa_exacta"] is None


def test_jaccard_de_conjuntos_vacios():
    assert _jaccard(set(), set()) == 1.0
    assert _jaccard({1}, set()) == 0.0
    assert _jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)


# --- Corpus -----------------------------------------------------------------


def test_el_corpus_real_carga_y_es_valido():
    casos = cargar_casos()
    assert len(casos) >= 8
    assert sum(1 for c in casos if not c["citations"]) >= 2
    assert any(len(c["citations"]) >= 3 for c in casos)
    assert any(not c["citations"] for c in casos)


def test_los_casos_reales_sin_citations_rechazan_la_salida_de_ejemplo():
    for caso_real in cargar_casos():
        if caso_real["citations"]:
            continue
        # La salida de ejemplo cita [1] y [2]; contra un caso sin citations
        # provistas eso debe fallar la validacion de citas.
        score = score_output(SALIDA_PERFECTA, caso_real)
        assert score["citas_validas"] is False


# --- El prompt real se construye para CADA caso (B1) -----------------------


def test_el_prompt_real_se_construye_para_cada_caso_del_corpus():
    """Cada caso del golden set debe poder armar un prompt via ``_build_prompt``.

    Antes del fix B1, el runner llamaba a ``_build_prompt`` con un quinto
    argumento (``descripcion``) que la firma no acepta. Cada invocacion
    levantaba ``TypeError`` y el runner la tragaba con un ``except``
    generico, asi que el harness reportaba 0 ejecuciones y nadie se enteraba
    de que en realidad no estaba midiendo nada. Esta prueba es el gate que
    evita volver a esa situacion: por cada caso del corpus, el prompt se
    debe poder construir sin excepcion, salir no vacio, y contener el
    ``project_name`` que el caso declara.

    El nombre del caso (``nombre``) y su descripcion larga NO son
    obligatorios en el output -- el prompt de produccion solo lleva
    ``project_name``, ``citations`` y ``feedback/prior_content``
    opcionales. La descripcion del YAML queda como campo documental.
    """
    from app.core.proposal_generator import _build_prompt

    casos = cargar_casos()
    assert casos, "el corpus real no puede estar vacio"

    for caso in casos:
        prompt = _build_prompt(
            caso["citations"],
            None,
            None,
            caso["project_name"],
        )
        assert isinstance(prompt, str) and prompt, (
            f"el prompt para {caso['id']} salio vacio"
        )
        assert caso["project_name"] in prompt, (
            f"el prompt para {caso['id']} no contiene el project_name"
        )
        # El contrato del prompt exige las tres secciones (con tilde).
        assert "## Componentes" in prompt
        assert "## Tecnologías" in prompt
        assert "## Patrones" in prompt


def test_dry_run_devuelve_no_cero_si_build_prompt_falla():
    """Si el prompt de produccion revienta, dry_run NO debe reportar OK.

    Repro del B1: antes, la llamada con 5 argumentos levantaba TypeError,
    el except del dry_run lo tragaba, imprimia "[AVISO]" y devolvia 0.
    Asi que el harness siempre daba verde aunque no pudiera medir nada.
    Despues del fix, ``dry_run`` propaga el fallo (exit code 1).
    """
    from unittest.mock import patch
    from evals.runner import dry_run

    casos = cargar_casos()
    with patch(
        "app.core.proposal_generator._build_prompt",
        side_effect=RuntimeError("exploto el prompt"),
    ):
        exit_code = dry_run(casos)

    assert exit_code != 0, (
        "dry_run devolvio 0 con _build_prompt roto: el harness "
        "estaria reportando OK mientras no puede medir nada."
    )


def test_ejecutar_corrida_devuelve_uno_si_todas_las_invocaciones_fallaron():
    """Si TODOS los triples (caso, modelo, repeat) fallaron, exit 1.

    Distinguir "la app dio OK con metricas 0" de "la app nunca llego a
    ejecutarse" es lo que hace util al harness en CI: el segundo caso
    tiene que prender una alarma. Antes del fix B1, ``ejecutar_corrida``
    devolvia 0 siempre.
    """
    import argparse
    from unittest.mock import MagicMock, patch
    from evals.runner import ejecutar_corrida

    # Forzamos que ``construir_modelo`` "funcione" (devuelve un mock de
    # chat) pero ``chat.invoke`` siempre tire. Asi el loader no rompe
    # pero las ejecuciones terminan todas con ``ok=False``.
    chat_mock = MagicMock()
    chat_mock.invoke.side_effect = RuntimeError("rate limit eterno")

    args = argparse.Namespace(
        models="m1",
        case=None,
        repeats=1,
        temperature=0.0,
        sleep=0.0,
        dry_run=False,
    )

    env = {
        "LLM_BASE_URL": "https://api.groq.com/openai/v1",
        "LLM_API_KEY": "gsk-fake",
        "LLM_MODEL": "m1",
    }
    with patch.dict("os.environ", env), \
         patch("evals.runner.construir_modelo", return_value=chat_mock):
        exit_code = ejecutar_corrida(args)

    assert exit_code == 1, (
        "ejecutar_corrida devolvio 0 aunque todos los triples fallaron: "
        "CI no podria distinguir 'midio y dio 0' de 'nunca ejecuto'."
    )


# --- Filtro de peores (I8) -------------------------------------------------


def test_filtrar_peores_separa_all_failed_de_peores_con_datos():
    """El listado "peor" no debe tragarse los pares donde TODO fallo.

    Antes del fix, ``peor = [v for v in variabilidad if (v.get("tasa_exacta")
    or 1.0) < 1.0]``. Cuando ``tasa_exacta`` era None (todos los repeats
    fallaron), ``None or 1.0 == 1.0`` y el par quedaba excluido del listado
    -- justo lo opuesto a lo que sirve para diagnosticar.

    La regla que estamos testeando: ``peor`` agrupa pares con variabilidad
    observada (tasa_exacta < 1.0); ``all_failed`` agrupa los pares sin
    datos suficientes. Las dos listas son disjuntas y entre las dos suman
    la variabilidad completa.
    """
    from evals.runner import _filtrar_peores

    variabilidad = [
        # Caso "malo": algunos repeats identicos, otros no. tasa_exacta < 1.0.
        {"caso_id": "c1", "modelo": "m1", "tasa_exacta": 0.5},
        # Caso "perfecto": todos los repeats identicos. tasa_exacta == 1.0.
        # No es "peor" ni "all_failed": queda fuera de ambas listas.
        {"caso_id": "c2", "modelo": "m1", "tasa_exacta": 1.0},
        # Caso "all-failed": tasa_exacta == None (0 o 1 repeats_ok).
        {"caso_id": "c3", "modelo": "m1", "tasa_exacta": None},
        # Otro "all-failed" para probar que se preservan todos los registros.
        {"caso_id": "c4", "modelo": "m2", "tasa_exacta": None},
        # "Peor" con tasa_exacta == 0.0 (peor de los peores).
        {"caso_id": "c5", "modelo": "m1", "tasa_exacta": 0.0},
    ]

    resultado = _filtrar_peores(variabilidad)

    assert {v["caso_id"] for v in resultado["peor"]} == {"c1", "c5"}
    assert {v["caso_id"] for v in resultado["all_failed"]} == {"c3", "c4"}
    # Las dos listas son disjuntas (mismo caso_id/modelo no aparece en ambas)
    ids_peor = {(v["caso_id"], v["modelo"]) for v in resultado["peor"]}
    ids_failed = {(v["caso_id"], v["modelo"]) for v in resultado["all_failed"]}
    assert ids_peor.isdisjoint(ids_failed)


def test_filtrar_peores_con_lista_vacia_devuelve_dos_listas_vacias():
    from evals.runner import _filtrar_peores

    resultado = _filtrar_peores([])

    assert resultado == {"peor": [], "all_failed": []}


def test_filtrar_peores_solo_identicos_no_aparecen_en_peor():
    """Variabilidad == 1.0 (todos los repeats identicos byte a byte) no
    es "peor": son modelos perfectamente reproducibles."""
    from evals.runner import _filtrar_peores

    variabilidad = [
        {"caso_id": "c1", "modelo": "m1", "tasa_exacta": 1.0},
        {"caso_id": "c2", "modelo": "m1", "tasa_exacta": 1.0},
    ]

    resultado = _filtrar_peores(variabilidad)

    assert resultado["peor"] == []
    assert resultado["all_failed"] == []


# --- Construccion del modelo: el runner NO debe duplicar la logica de prod ---


def test_construir_modelo_omite_temperature_para_serie_o():
    """El runner debe respetar la misma omision de temperature que la app.

    Antes del I6, ``construir_modelo`` llamaba ``init_chat_model`` directo con
    ``temperature=...`` siempre. Si el usuario del harness queria medir la
    serie o* (que solo admite 1), terminaba con un 400 silencioso. El fix
    centraliza la regla en ``app.core.llm_loader._build_chat_model``, igual
    que produccion, y el runner la consume en vez de duplicarla.
    """
    from unittest.mock import patch

    with patch("app.core.llm_loader.init_chat_model") as mock_init:
        mock_init.return_value = MagicMock() if False else None  # type: ignore
        construir_modelo(
            modelo="o1-mini",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            temperature=0.0,
        )

    # Si el helper del runner no omite temperature, init_chat_model la recibe
    # y OpenAI responde 400 al primer token.
    kwargs = mock_init.call_args.kwargs
    assert "temperature" not in kwargs


def test_construir_modelo_manda_temperature_para_familia_comun():
    """El runner sigue mandando temperature para modelos que la soportan."""
    from unittest.mock import patch, MagicMock

    with patch("app.core.llm_loader.init_chat_model") as mock_init:
        mock_init.return_value = MagicMock()
        construir_modelo(
            modelo="gpt-4o-mini",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            temperature=0.0,
        )

    kwargs = mock_init.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["model_provider"] == "openai"
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["api_key"] == "sk-test"
