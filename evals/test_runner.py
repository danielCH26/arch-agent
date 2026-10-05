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
    "## Tecnologias\n"
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


def test_titulo_con_tilde_en_tecnologias_no_cumple_el_contrato():
    """El prompt real pide 'Tecnologias' SIN tilde; el scorer es estricto a proposito."""
    con_tilde = SALIDA_PERFECTA.replace("## Tecnologias", "## Tecnologías")
    score = score_output(con_tilde, caso())
    assert score["secciones_ok"] is False


# --- Orden ------------------------------------------------------------------


def test_orden_correcto_de_las_tres_secciones():
    score = score_output(SALIDA_PERFECTA, caso())
    assert score["orden_ok"] is True


def test_orden_incorrecto_es_fallo():
    desordenado = (
        "## Patrones\n- Arquitectura en capas (Layered) [1]\n\n"
        "## Componentes\n- API de pedidos [1]\n\n"
        "## Tecnologias\n- Python\n"
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
        "## Tecnologias\n- Python\n\n"
        "## Patrones\n- Patron C [3]\n"
    )
    score = score_output(texto, tres)
    assert score["citas_validas"] is True
    assert score["marcadores"] == [3, 3]


def test_cita_fuera_de_rango_es_invalida():
    texto = (
        "## Componentes\n- Componente [9]\n\n"
        "## Tecnologias\n- Python\n\n"
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
        "## Tecnologias\n- Python\n\n"
        "## Patrones\n- No aplica\n"
    )
    score = score_output(texto, caso([]))
    assert score["citas_validas"] is False
    assert score["pass_estructural"] is False


def test_caso_sin_citations_sin_marcadores_pasa_citas():
    texto = (
        "## Componentes\n- Script cron\n\n"
        "## Tecnologias\n- Python\n\n"
        "## Patrones\n- No aplica a este caso\n"
    )
    score = score_output(texto, caso([]))
    assert score["citas_validas"] is True


def test_enlace_markdown_no_cuenta_como_cita():
    texto = (
        "## Componentes\n- API [documentacion](#api)\n\n"
        "## Tecnologias\n- Python\n\n"
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
    assert score["bullets_por_seccion"]["Tecnologias"] == 2
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
    assert SECCIONES_REQUERIDAS == ("Componentes", "Tecnologias", "Patrones")


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
        "## Tecnologias\n- Python\n\n"
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
