"""
Tests para el agente de elicitación (parseo de JSON del LLM, reglas duras
de preguntas, y manejo de errores del proveedor).

Issue: [F05] Elicitación guiada + aprobación
Revisión de PR #63: agrega el caso de fence sin la palabra 'json' que
faltaba cubrir con un test unitario.
"""

import logging
import re

import pytest

from app.core import elicitation_agent
from app.core.elicitation_agent import (
    ElicitationAgentError,
    ElicitationLLMError,
    FIRST_QUESTION,
    MAX_QUESTIONS,
    NEXT_STEP_SYSTEM_PROMPT,
    _es_pregunta_compuesta,
    _extract_json_object,
    _strip_json_fences,
    generate_summary,
    next_step,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    """Modelo LangChain simulado: responde en orden con lo que se le indique."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        # config (callbacks, run_name) de cada invocación; None si no se pasó.
        self.configs = []

    def invoke(self, messages, config=None):
        self.calls.append(messages)
        self.configs.append(config)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _FakeMessage(response)


HISTORY_1 = [{"pregunta": "p0", "respuesta": "r0"}]
HISTORY_5 = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(5)]
HISTORY_10 = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(10)]

# Historiales que ya cubren los factores de viabilidad obligatorios
# (presupuesto, equipo, plazo). Sin esto, a partir del mínimo de preguntas la
# regla de viabilidad responde antes que el LLM y el guardarraíl de preguntas
# compuestas nunca llega a ejecutarse. Los tests del guardarraíl los usan para
# aislar su comportamiento de esa regla.
_RESPUESTA_VIABILIDAD = (
    "Presupuesto de 20000 USD, equipo de 3 desarrolladores y plazo de 3 meses."
)
HISTORY_1_VIABLE = [{"pregunta": "p0", "respuesta": _RESPUESTA_VIABILIDAD}]
# Documentos que cubren la checklist completa (usuarios, funcionalidades,
# calidad y los tres factores de viabilidad): con ellos el modelo puede cerrar.
_DOCS_COMPLETOS = (
    "Usuarios: operadores de bodega. Deben poder registrar inventario. "
    "Seguridad básica. Presupuesto definido. Equipo disponible. Plazo acordado. "
    "App web. El equipo domina Python. Los operadores ingresan los datos a mano."
)
HISTORY_5_VIABLE = HISTORY_1_VIABLE + HISTORY_5[1:]


class TestStripJsonFences:
    def test_fence_with_json_tag(self):
        raw = '```json\n{"done": true}\n```'
        assert _strip_json_fences(raw) == '{"done": true}'

    def test_fence_without_json_tag(self):
        # Caso señalado en revisión de PR #63: sin la palabra 'json', el
        # '\n' no debe quedar pegado al JSON.
        raw = '```\n{"done": true}\n```'
        assert _strip_json_fences(raw) == '{"done": true}'

    def test_no_fence_at_all(self):
        raw = '{"done": false}'
        assert _strip_json_fences(raw) == '{"done": false}'


class TestExtractJsonObject:
    def test_extracts_from_think_block(self):
        raw = '<think>razonando...</think>\n{"done": true}'
        assert _extract_json_object(raw) == '{"done": true}'

    def test_extracts_with_surrounding_prose(self):
        raw = 'aquí va: {"done": false, "question": "¿algo?"} gracias'
        assert _extract_json_object(raw) == '{"done": false, "question": "¿algo?"}'

    def test_returns_text_unchanged_if_no_braces(self):
        assert _extract_json_object("sin json aquí") == "sin json aquí"


class TestEsPreguntaCompuesta:
    @pytest.mark.parametrize(
        "pregunta",
        [
            # Bloques interrogativos apilados (2 cierres '?').
            "¿Quiénes son los usuarios principales? "
            "¿Qué funcionalidades críticas necesitan?",
            # Caso del issue #100: un solo '?', dos preguntas unidas con "y".
            "¿Quiénes son los usuarios principales y qué funcionalidades "
            "críticas necesitan?",
            "¿Cuántos usuarios esperan tener y cómo se autenticarían?",
            "¿Quiénes son y cuántos serían?",
            "¿Qué problema resuelve o para quién es?",
            "¿Qué tan seguido lo usarían y por qué?",
            "¿Qué usuarios usan el sistema y con quién se integran?",
            # Mayúsculas en el conector / palabra interrogativa.
            "¿Quiénes son los usuarios Y Qué necesitan?",
        ],
    )
    def test_preguntas_compuestas_se_detectan(self, pregunta):
        assert _es_pregunta_compuesta(pregunta) is True

    @pytest.mark.parametrize(
        "pregunta",
        [
            "¿Quiénes son los usuarios principales del sistema?",
            # "y" entre sustantivos dentro de UNA sola interrogación.
            "¿Qué frameworks y bases de datos usan?",
            "¿Qué restricciones de tiempo y presupuesto tienen?",
            # Sin tilde, "como"/"que"/"cuando" son conjunciones o relativos,
            # no interrogativos: no deben contar como segunda pregunta.
            "¿Qué usuarios usan el sistema y como administradores?",
            "¿Necesitan que el sistema funcione offline o cuando haya red?",
            "¿Qué datos se guardan y que sean auditables?",
        ],
    )
    def test_preguntas_granulares_no_se_marcan(self, pregunta):
        assert _es_pregunta_compuesta(pregunta) is False

    def test_sin_cierres_interrogativos_no_es_compuesta(self):
        assert _es_pregunta_compuesta("") is False
        assert _es_pregunta_compuesta("Cuéntame más sobre las restricciones") is False

    @pytest.mark.parametrize("valor", [None, 42, ["¿a?", "¿b?"]])
    def test_tipo_inesperado_no_rompe_y_no_es_compuesta(self, valor):
        # Fail-open: un tipo inesperado no debe romper el flujo del agente.
        assert _es_pregunta_compuesta(valor) is False


class TestNextStepPromptGranularidad:
    """Issue #100 opción A: el prompt prohíbe explícitamente la pregunta
    compuesta y exige granularidad (el prompt ES el artefacto, el test de
    contenido es legítimo acá)."""

    def test_prompt_prohibe_pregunta_compuesta_y_exige_una_dimension(self):
        assert "UNA sola dimensión" in NEXT_STEP_SYSTEM_PROMPT
        assert "Prohibida la pregunta compuesta" in NEXT_STEP_SYSTEM_PROMPT

    def test_prompt_exige_granularidad_respondible_en_una_o_dos_oraciones(self):
        assert "una o dos oraciones" in NEXT_STEP_SYSTEM_PROMPT

    def test_prompt_exige_un_solo_aspecto_dentro_de_cada_dimension(self):
        # "Una sola dimensión" por sí sola deja pasar "¿Quiénes son y cuántos
        # serían?" (ambos son de Usuarios): la regla baja un nivel más.
        assert "un solo aspecto a la vez" in NEXT_STEP_SYSTEM_PROMPT

    def test_prompt_incluye_ejemplo_compuesto_malo(self):
        assert "MALA (compuesta)" in NEXT_STEP_SYSTEM_PROMPT
        assert (
            "¿Quiénes son los usuarios principales y qué funcionalidades "
            "críticas necesitan?" in NEXT_STEP_SYSTEM_PROMPT
        )

    def test_prompt_incluye_ejemplo_granular_bueno(self):
        assert "BUENA (granular)" in NEXT_STEP_SYSTEM_PROMPT
        assert (
            "¿Quiénes son los usuarios principales del sistema?"
            in NEXT_STEP_SYSTEM_PROMPT
        )

    def test_prompt_mantiene_las_4_categorias_y_contrato_json(self):
        # Regresión: las reglas nuevas no reemplazan lo existente.
        for categoria in ("Usuarios", "Funcionalidades", "Restricciones", "Calidad"):
            assert categoria in NEXT_STEP_SYSTEM_PROMPT
        assert '"done": bool' in NEXT_STEP_SYSTEM_PROMPT
        assert '"question"' in NEXT_STEP_SYSTEM_PROMPT


PREGUNTA_COMPUESTA = (
    "¿Quiénes son los usuarios principales? "
    "¿Qué funcionalidades críticas necesitan?"
)
PREGUNTA_GRANULAR = "¿Quiénes son los usuarios principales del sistema?"
# Caso del issue #100: un solo '?' con dos interrogaciones unidas por "y".
PREGUNTA_COMPUESTA_UN_SIGNO = (
    "¿Quiénes son los usuarios principales y qué funcionalidades "
    "críticas necesitan?"
)


class TestNextStepRetryPreguntaCompuesta:
    """Issue #100 opción C: una pregunta evidentemente compuesta dispara
    UN reintento correctivo; si el reintento devuelve una pregunta
    granular, se usa esa."""

    def test_pregunta_compuesta_dispara_reintento_y_usa_la_granular(self):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        decision = next_step(model, history=HISTORY_5_VIABLE)
        assert decision.done is False
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 2

    def test_pregunta_del_issue_con_un_solo_signo_dispara_reintento(self):
        # El caso que motivó el issue #100: un solo '?', dos preguntas.
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA_UN_SIGNO}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        decision = next_step(model, history=HISTORY_5_VIABLE)
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 2

    def test_reintento_reusa_el_mismo_contexto_con_instruccion_correctiva(self):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        next_step(model, history=HISTORY_5_VIABLE)
        mensajes_reintento = model.calls[1]
        contexto = mensajes_reintento[1].content
        assert "UNA sola pregunta sobre UN solo tema" in contexto
        # El historial original viaja en el reintento (mismo seam de invocación).
        assert "p0" in contexto

    def test_reintento_incluye_la_pregunta_rechazada(self):
        # Sin la pregunta rechazada el modelo tendría que adivinar qué
        # corregir y probablemente repetiría lo mismo.
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        next_step(model, history=HISTORY_5_VIABLE)
        contexto_principal = model.calls[0][1].content
        contexto_reintento = model.calls[1][1].content
        assert PREGUNTA_COMPUESTA in contexto_reintento
        # La pregunta rechazada solo viaja en el reintento (efímera).
        assert PREGUNTA_COMPUESTA not in contexto_principal

    def test_reintento_usa_run_name_propio_y_propaga_callbacks(self):
        callback = object()
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        next_step(model, history=HISTORY_5_VIABLE, callbacks=[callback])
        assert model.configs[0] == {
            "callbacks": [callback],
            "run_name": "elicitation-next-step",
        }
        assert model.configs[1] == {
            "callbacks": [callback],
            "run_name": "elicitation-next-step-retry",
        }


class TestNextStepFailOpenPreguntaCompuesta:
    """Fail-open (Issue #100): si el reintento no arregla la pregunta, se
    devuelve la original con warning -- nunca se eleva un error al usuario."""

    def _decision_con_reintento(self, caplog, respuesta_reintento):
        model = _FakeModel(
            [
                f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                respuesta_reintento,
            ]
        )
        with caplog.at_level(logging.WARNING, logger="app.core.elicitation_agent"):
            decision = next_step(model, history=HISTORY_5_VIABLE)
        assert len(model.calls) == 2
        # Siempre se devuelve la decisión original, sin raise.
        assert decision.done is False
        assert decision.question == PREGUNTA_COMPUESTA
        return caplog.text.lower()

    def test_reintento_tambien_compuesto_devuelve_original_con_warning(self, caplog):
        texto = self._decision_con_reintento(
            caplog,
            f'{{"done": false, "question": "{PREGUNTA_GRANULAR} ¿seguro?", "reason": "y"}}',
        )
        assert "pese al reintento" in texto
        assert PREGUNTA_COMPUESTA.lower() in texto

    def test_reintento_no_parseable_devuelve_original_sin_raise(self, caplog):
        texto = self._decision_con_reintento(caplog, "esto no es json")
        assert "falló al invocar o parsear" in texto
        assert "elicitationagenterror" in texto

    def test_reintento_json_sin_clave_done_devuelve_original_con_warning(self, caplog):
        # Si el reintento devuelve JSON parseable pero sin la clave 'done',
        # se devuelve la original con warning.
        texto = self._decision_con_reintento(
            caplog, '{"question": "¿algo granular?", "reason": "sin done"}'
        )
        assert "sin la clave" in texto

    def test_reintento_con_done_true_devuelve_original_con_warning(self, caplog):
        # done=true no sirve como pregunta a mostrar: se devuelve la original.
        texto = self._decision_con_reintento(
            caplog, '{"done": true, "question": null, "reason": "listo"}'
        )
        assert "done=true" in texto
        # El log distingue este caso del de "pregunta todavía compuesta".
        assert "pese al reintento" not in texto

    def test_reintento_con_error_de_invocacion_devuelve_original_con_warning(self, caplog):
        # El caso real de 429 / timeout del LLM viaja como
        # ElicitationLLMError (distinto de un error de parseo de JSON).
        texto = self._decision_con_reintento(
            caplog, RuntimeError("Error code: 429 - rate_limit_exceeded")
        )
        assert "falló al invocar" in texto
        assert "elicitationllmerror" in texto

    @pytest.mark.parametrize("escalar", ["null", "42", '"texto"', "[1, 2]"])
    def test_reintento_con_json_que_no_es_objeto_devuelve_original(self, caplog, escalar):
        # Antes: `"done" not in data` lanzaba TypeError con null/42 y
        # llegaba a la API como un 500.
        texto = self._decision_con_reintento(caplog, escalar)
        assert "no es un objeto" in texto

    def test_reintento_con_contenido_en_bloques_devuelve_original(self, caplog):
        # response.content puede ser una lista de bloques (en vez de str):
        # _strip_json_fences lanzaba AttributeError, que no es un
        # ElicitationAgentError.
        texto = self._decision_con_reintento(
            caplog, [{"type": "text", "text": '{"done": false}'}]
        )
        assert "falló al invocar o parsear" in texto

    @pytest.mark.parametrize(
        "pregunta_json",
        ["null", '""', '"   "', '["¿a?", "¿b?"]', "42"],
        ids=["nula", "vacia", "solo_espacios", "lista", "numero"],
    )
    def test_reintento_con_pregunta_invalida_devuelve_original(
        self, caplog, pregunta_json
    ):
        # Una pregunta nula, vacía o que no es texto no puede persistirse
        # como pending_question.
        texto = self._decision_con_reintento(
            caplog,
            f'{{"done": false, "question": {pregunta_json}, "reason": "y"}}',
        )
        assert "vacía o que no es texto" in texto


class TestNextStepSinReintento:
    """Regresión (Issue #100): el guardarraíl no debe agregar llamadas al
    LLM cuando no hay pregunta compuesta, ni en los caminos deterministas."""

    def test_pregunta_granular_hace_una_sola_llamada(self):
        model = _FakeModel(
            [f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "x"}}']
        )
        decision = next_step(model, history=HISTORY_5_VIABLE)
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 1

    def test_pregunta_compuesta_al_maximo_se_fuerza_done_sin_reintento(self):
        # Al llegar al máximo la regla dura fuerza done=True y descarta la
        # pregunta: reintentar sería una llamada desperdiciada.
        model = _FakeModel(
            [f'{{"done": false, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}']
        )
        decision = next_step(model, history=HISTORY_10)
        assert decision.done is True
        assert decision.question is None
        assert len(model.calls) == 1

    def test_compuesta_forzada_por_minimo_tambien_se_reintenta(self):
        # done=true antes del mínimo conserva la pregunta del modelo (acá
        # compuesta); la regla dura la deja en done=False y el reintento
        # opera sobre la decisión final.
        model = _FakeModel(
            [
                f'{{"done": true, "question": "{PREGUNTA_COMPUESTA}", "reason": "x"}}',
                f'{{"done": false, "question": "{PREGUNTA_GRANULAR}", "reason": "y"}}',
            ]
        )
        decision = next_step(model, history=HISTORY_1_VIABLE)
        assert decision.done is False
        assert decision.question == PREGUNTA_GRANULAR
        assert len(model.calls) == 2


class TestNextStepFirstQuestion:
    def test_first_question_is_deterministic_and_skips_llm(self):
        model = _FakeModel([])  # no debe consumirse ninguna respuesta
        decision = next_step(model, history=[])
        assert decision.done is False
        assert decision.question == FIRST_QUESTION
        assert model.calls == []

    def test_first_question_is_one_dimension_not_compound(self):
        # FIRST_QUESTION es la primera pregunta que el usuario ve y NO
        # pasa por el guardarraíl de preguntas compuestas (next_step
        # retorna antes de invocar al LLM cuando history está vacía), así
        # que debe ser una sola dimensión. Si combina 'problema' con
        # 'usuarios' (con 'y' o con un 'para quién es' implícito), el
        # detector no la atrapa. Esta es una prueba de intención: la
        # pregunta no debe nombrar dos categorías del prompt a la vez.
        pregunta_lower = FIRST_QUESTION.lower()
        menciona_problema = "problema" in pregunta_lower
        # 'usuarios' aparece literal, o como 'para quién' / 'quienes
        # son' (que implican la categoría). Heurística conservadora a
        # propósito: preferimos falsos negativos a romper reformulaciones
        # legítimas del LLM en turnos posteriores.
        menciona_usuarios = (
            "usuarios" in pregunta_lower
            or "para quién" in pregunta_lower
            or "quiénes son" in pregunta_lower
        )
        assert not (menciona_problema and menciona_usuarios), (
            f"FIRST_QUESTION no debe combinar 'problema' y 'usuarios' en "
            f"la misma pregunta (Issue #100): "
            f"{FIRST_QUESTION!r}"
        )

    def test_first_question_uses_relevant_documents_when_available(self):
        model = _FakeModel([
            '{"done": false, "question": "El acta define el alcance. ¿Qué usuario atenderá primero?", "reason": "faltan usuarios"}'
        ])

        decision = next_step(
            model,
            history=[],
            project_description="Sistema de inventario",
            documents_context=(
                "### Documento: acta.md\nEl sistema debe registrar inventario de "
                "bodegas. Presupuesto de 10 millones COP. Equipo de 3 personas. "
                "Plazo de 3 meses."
            ),
        )

        assert decision.done is False
        assert "usuario" in (decision.question or "").lower()
        assert len(model.calls) == 1
        prompt_context = model.calls[0][1].content
        assert "inventario de bodegas" in prompt_context
        assert "No hay respuestas todavía" in prompt_context


class TestPreguntasForzadasSonGranulares:
    """Las preguntas que el agente devuelve SIN pasar por el LLM (la primera
    pregunta y las de viabilidad obligatoria) tampoco pasan por el
    guardarraíl de reintento. Por eso se fija aquí que ninguna sea
    compuesta (Issue #100)."""

    def test_first_question_no_es_compuesta(self):
        assert not _es_pregunta_compuesta(FIRST_QUESTION)

    @pytest.mark.parametrize(
        "factor, pregunta",
        [(name, question) for name, _patterns, question in elicitation_agent._VIABILITY_FACTORS],
    )
    def test_preguntas_de_viabilidad_no_son_compuestas(self, factor, pregunta):
        assert not _es_pregunta_compuesta(pregunta), (factor, pregunta)


class TestRegistroTuteo:
    """El producto entero está en tuteo: el voseo mezclado en un mismo texto
    (ej. "Cuéntame ... querés") es visible para el usuario y delata
    inconsistencia. Guarda contra regresiones en los textos del módulo."""

    _VOSEO = re.compile(
        r"\b(querés|podés|tenés|sabés|decís|cubrí|dividí|devolvé|contame|"
        r"decime|escribí|elegí|describí|respondé|hacé|fijate|mirá|usá|"
        r"pensá|ponete|vos)\b",
        re.IGNORECASE,
    )

    @pytest.mark.parametrize(
        "nombre",
        [
            "FIRST_QUESTION",
            "NEXT_STEP_SYSTEM_PROMPT",
            "SUMMARY_SYSTEM_PROMPT",
            "_CORRECCION_PREGUNTA_COMPUESTA",
        ],
    )
    def test_los_textos_del_agente_no_usan_voseo(self, nombre):
        texto = getattr(elicitation_agent, nombre)
        assert not self._VOSEO.search(texto), self._VOSEO.search(texto).group(0)

    def test_fallback_del_minimo_no_usa_voseo(self):
        texto = elicitation_agent.MIN_QUESTIONS_FALLBACK
        assert not self._VOSEO.search(texto), self._VOSEO.search(texto).group(0)

    @pytest.mark.parametrize(
        "factor, pregunta",
        [(name, question) for name, _patterns, question in elicitation_agent._VIABILITY_FACTORS],
    )
    def test_preguntas_de_viabilidad_no_usan_voseo(self, factor, pregunta):
        assert not self._VOSEO.search(pregunta), (factor, self._VOSEO.search(pregunta).group(0))


class TestNextStepHardRules:
    def test_forces_not_done_before_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert decision.question is not None

    def test_respects_done_after_min_questions(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ok"}'])
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context=_DOCS_COMPLETOS,
        )
        assert decision.done is True

    def test_forces_done_at_max_questions(self):
        model = _FakeModel(['{"done": false, "question": "otra", "reason": "sigo"}'])
        decision = next_step(
            model,
            history=HISTORY_10,
            documents_context=_DOCS_COMPLETOS,
        )
        assert decision.done is True

    def test_requires_budget_team_and_timeline_before_finishing(self):
        history = [
            {"pregunta": f"pregunta {index}", "respuesta": "respuesta detallada"}
            for index in range(5)
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])

        decision = next_step(model, history=history)

        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()
        assert "viabilidad" in decision.reason

    def test_allows_finishing_when_viability_factors_are_known(self):
        history = [
            {"pregunta": "usuarios", "respuesta": "Operadores de bodega."},
            {"pregunta": "funciones", "respuesta": "Registrar inventario."},
            {"pregunta": "presupuesto", "respuesta": "Presupuesto máximo de 20 millones COP."},
            {"pregunta": "equipo", "respuesta": "Equipo de 3 desarrolladores senior."},
            {"pregunta": "plazo", "respuesta": "MVP en 12 semanas."},
            {"pregunta": "calidad", "respuesta": "Que sea seguro y rápido."},
            {"pregunta": "plataforma", "respuesta": "Web, en Python; los datos los registran los operadores."},
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])

        decision = next_step(model, history=history)

        assert decision.done is True


class TestNextStepParsingEdgeCases:
    def test_handles_fence_without_json_tag(self):
        model = _FakeModel(['```\n{"done": false, "question": "¿otra?", "reason": "x"}\n```'])
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context=_DOCS_COMPLETOS,
        )
        assert decision.question == "¿otra?"

    def test_handles_think_block_before_json(self):
        model = _FakeModel(
            ['<think>pensando mucho</think>\n{"done": true, "question": null, "reason": "listo"}']
        )
        decision = next_step(
            model,
            history=HISTORY_5,
            documents_context=_DOCS_COMPLETOS,
        )
        assert decision.done is True

    def test_raises_on_invalid_json(self):
        model = _FakeModel(["esto no es json"])
        with pytest.raises(ElicitationAgentError):
            next_step(model, history=HISTORY_5)


class TestLLMErrorHandling:
    def test_provider_exception_becomes_elicitation_llm_error(self):
        model = _FakeModel([RuntimeError("Error code: 429 - rate_limit_exceeded")])
        with pytest.raises(ElicitationLLMError):
            next_step(model, history=HISTORY_5)

    def test_elicitation_llm_error_is_subclass_of_agent_error(self):
        assert issubclass(ElicitationLLMError, ElicitationAgentError)


class TestGenerateSummary:
    def test_parses_summary_shape(self):
        model = _FakeModel(
            [
                '{"problema": "x", "usuarios": "y", "funcionalidades": [], '
                '"restricciones": [], "calidad": []}'
            ]
        )
        summary = generate_summary(model, history=HISTORY_5)
        assert summary["problema"] == "x"
        assert set(summary.keys()) == {
            "problema", "usuarios", "funcionalidades", "restricciones", "calidad"
        }

    def test_quality_origin_is_kept_apart_from_the_attribute_list(self):
        model = _FakeModel(
            [
                '{"problema": "x", "usuarios": "y", "funcionalidades": ["a"], '
                '"restricciones": [], "calidad": ['
                '{"atributo": "Seguridad", "origen": "dicho"}, '
                '{"atributo": "Disponibilidad", "origen": "propuesto"}]}'
            ]
        )
        summary = generate_summary(model, history=HISTORY_5)
        assert summary["calidad"] == ["Seguridad", "Disponibilidad"]
        assert summary["calidad_origen"] == {
            "Seguridad": "dicho",
            "Disponibilidad": "propuesto",
        }

    def test_summary_prompt_asks_for_the_origin_of_each_quality_attribute(self):
        assert '"origen": "dicho" | "propuesto"' in elicitation_agent.SUMMARY_SYSTEM_PROMPT


# --- Verificación de viabilidad (review #5 y #6) ---------------------------

from app.core.elicitation_agent import (  # noqa: E402
    _VIABILITY_FACTORS,
    _missing_viability_factors,
)


def _missing(history, description="", documents=None):
    return [name for name, _ in _missing_viability_factors(history, description, documents)]


class TestMissingViabilityFactors:
    def test_generic_question_text_does_not_cover_team_or_deadline(self):
        history = [
            {"pregunta": "¿Cuántas personas usarán el sistema?", "respuesta": "Unas 50"},
            {"pregunta": "¿Qué tiempo de respuesta esperan?", "respuesta": "Menos de 2 s"},
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_question_text_alone_never_counts(self):
        history = [
            {"pregunta": "¿Cuál es el presupuesto, el equipo y el plazo?", "respuesta": "No sé"},
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_keywords_need_word_boundaries(self):
        history = [
            {
                "pregunta": "p",
                "respuesta": "Reservas de mesa, una promesa de servicio y hacemos copia diaria",
            }
        ]
        assert _missing(history) == ["presupuesto", "equipo", "plazo"]

    def test_old_team_question_already_answered_is_not_asked_again(self):
        # Sesión que estaba en curso al hacer el deploy: respondió la versión
        # vieja (compuesta) de la pregunta del equipo con algo que la regex no
        # reconoce. No debe recibir la pregunta nueva otra vez.
        history = [
            {
                "pregunta": elicitation_agent._LEGACY_VIABILITY_QUESTIONS["equipo"][0],
                "respuesta": "3 personas, 2 backend",
            },
        ]
        assert "equipo" not in _missing(history)

    def test_accented_words_are_recognized(self):
        history = [
            {"pregunta": "p", "respuesta": "Una inversión de 5.000 dólares"},
            {"pregunta": "p", "respuesta": "Equipo de 2 desarrolladores"},
            {"pregunta": "p", "respuesta": "Entrega en 3 meses"},
        ]
        assert _missing(history) == []

    def test_monthly_cost_and_real_time_are_not_a_deadline(self):
        history = [
            {"pregunta": "p", "respuesta": "Máximo 100 USD al mes. Equipo de 3."},
            {"pregunta": "p", "respuesta": "Necesitamos notificaciones en tiempo real"},
        ]
        assert _missing(history) == ["plazo"]

    def test_description_and_documents_still_count(self):
        assert _missing(
            [],
            "Presupuesto bajo",
            "Equipo de 3 personas. Plazo de 3 meses.",
        ) == []

    def test_answering_the_viability_question_with_unknown_closes_the_factor(self):
        budget_question = _VIABILITY_FACTORS[0][2]
        history = [{"pregunta": budget_question, "respuesta": "Aún no lo definimos"}]
        assert _missing(history) == ["equipo", "plazo"]


class TestViabilityRuleGating:
    def test_does_not_replace_the_llm_question_in_early_turns(self):
        for size in (1, 2, 3, 4):
            history = [{"pregunta": f"p{i}", "respuesta": f"r{i}"} for i in range(size)]
            model = _FakeModel(
                ['{"done": false, "question": "¿Qué usuarios tendrá?", "reason": "x"}']
            )
            decision = next_step(model, history=history)
            assert decision.question == "¿Qué usuarios tendrá?", size
            assert decision.done is False

    def test_applies_when_the_llm_wants_to_finish_early(self):
        model = _FakeModel(['{"done": true, "question": null, "reason": "ya"}'])
        decision = next_step(model, history=HISTORY_1)
        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()

    def test_applies_once_the_minimum_is_reached(self):
        model = _FakeModel(
            ['{"done": false, "question": "otra", "reason": "sigo"}']
        )
        decision = next_step(model, history=HISTORY_5)
        assert decision.done is False
        assert "presupuesto" in (decision.question or "").lower()
        assert "viabilidad" in decision.reason

    def test_never_asks_an_eleventh_question(self):
        model = _FakeModel(['{"done": false, "question": "otra", "reason": "sigo"}'])
        decision = next_step(model, history=HISTORY_10)
        assert decision.done is True
        assert decision.question is None

    def test_vague_answers_never_exceed_max_questions(self):
        model_response = '{"done": false, "question": "¿Qué usuarios tendrá?", "reason": "x"}'
        history = []
        for _ in range(MAX_QUESTIONS + 2):
            decision = next_step(_FakeModel([model_response]), history=history)
            if decision.done:
                break
            history.append({"pregunta": decision.question, "respuesta": "no sé"})
        assert decision.done is True
        assert len(history) == MAX_QUESTIONS


# --- Re-revisión: palabras del dominio y montos pegados a la moneda ---------

class TestViabilityRereview:
    def test_domain_words_do_not_cover_budget_or_team(self):
        description = "App para gestionar entregas de pedidos y equipos de gimnasio, reducir costos de envío"
        assert _missing([], description) == ["presupuesto", "equipo", "plazo"]

    def test_amount_glued_to_currency_counts_as_budget(self):
        for answer in ("5000usd", "20000cop", "USD 5000", "$20.000", "10 mil pesos", "5k usd"):
            history = [{"pregunta": "p", "respuesta": answer}]
            assert "presupuesto" not in _missing(history), answer

    def test_headcount_answers_count_as_team(self):
        for answer in ("somos 3", "somos tres", "un solo desarrollador", "3 desarrolladores", "desarrolladores senior"):
            history = [{"pregunta": "p", "respuesta": answer}]
            assert "equipo" not in _missing(history), answer

    def test_user_counts_are_not_a_team_size(self):
        history = [{"pregunta": "p", "respuesta": "500 personas usarán el sistema"}]
        assert "equipo" in _missing(history)

    def test_own_llm_team_question_answered_with_headcount_is_not_asked_again(self):
        history = [{"pregunta": "¿Cuántos devs son?", "respuesta": "somos 3"}]
        assert "equipo" not in _missing(history)


# --- Checklist de cobertura y preocupaciones del dominio -------------------

from app.core.elicitation_agent import (  # noqa: E402
    missing_coverage,
    pending_domain_questions,
    summary_gaps,
)

_VIABLE_ANSWERS = [
    {"pregunta": "presupuesto", "respuesta": "Presupuesto de 20000 USD."},
    {"pregunta": "equipo", "respuesta": "Equipo de 3 desarrolladores."},
    {"pregunta": "plazo", "respuesta": "MVP en 3 meses."},
]


class TestCoverageChecklist:
    def test_the_llm_cannot_close_without_asking_about_quality(self):
        # Caso real (Anexo A del ADR de mascotas): 10 preguntas, ninguna de
        # calidad, y el agente cerró igual.
        history = [
            {"pregunta": "¿Quiénes usarán el sistema?", "respuesta": "Vecinos del barrio."},
            {"pregunta": "¿Qué debe hacer?", "respuesta": "Registrar avisos de mascotas."},
            *_VIABLE_ANSWERS,
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "listo"}'])

        decision = next_step(model, history=history)

        assert decision.done is False
        assert "calidad" in decision.reason
        assert "rendimiento" in (decision.question or "")
        assert not _es_pregunta_compuesta(decision.question)

    def test_answering_the_quality_question_closes_the_category(self):
        question = dict(missing_coverage([{"pregunta": "p", "respuesta": "usuarios"}]))["calidad"]
        history = [{"pregunta": question, "respuesta": "No lo tenemos claro"}]
        assert "calidad" not in [name for name, _ in missing_coverage(history)]

    def test_questions_alone_do_not_cover_a_category(self):
        history = [{"pregunta": "¿Qué tan seguro debe ser?", "respuesta": ""}]
        assert "calidad" in [name for name, _ in missing_coverage(history)]

    def test_domain_concern_is_asked_before_closing(self):
        history = [
            {"pregunta": "¿Quiénes usarán el sistema?", "respuesta": "Dueños de mascotas perdidas."},
            {"pregunta": "¿Qué debe hacer?", "respuesta": "Publicar avisos."},
            {"pregunta": "calidad", "respuesta": "Que sea rápido."},
            {"pregunta": "plataforma", "respuesta": "App móvil en Flutter; los dueños suben los datos."},
            *_VIABLE_ANSWERS,
        ]
        model = _FakeModel(['{"done": true, "question": null, "reason": "listo"}'])

        decision = next_step(model, history=history)

        assert decision.done is False
        assert "dominio" in decision.reason
        assert "mapa" in (decision.question or "")

    def test_domain_questions_stop_after_the_limit(self):
        from app.core.domain_concerns import DOMAIN_CONCERNS

        base = [{"pregunta": "p", "respuesta": "Mascotas perdidas en el barrio"}]
        assert len(pending_domain_questions(base)) >= 2  # ubicación y archivos
        asked = [
            {"pregunta": concern.question, "respuesta": "no"}
            for concern in DOMAIN_CONCERNS[: elicitation_agent.MAX_DOMAIN_QUESTIONS]
        ]
        assert pending_domain_questions(base + asked) == []

    def test_backups_are_not_asked_during_elicitation(self):
        keys = [key for key, _ in pending_domain_questions([{"pregunta": "p", "respuesta": "Un CRUD simple"}])]
        assert "respaldos" not in keys


class TestSummaryGaps:
    def _complete(self, **overrides):
        summary = {
            "problema": "x",
            "usuarios": "Operadores",
            "funcionalidades": ["Registrar inventario"],
            "restricciones": ["Presupuesto de 20000 USD", "Equipo de 3 personas", "Plazo de 3 meses"],
            "calidad": ["Seguridad"],
        }
        summary.update(overrides)
        return summary

    def test_complete_summary_has_no_gaps(self):
        assert summary_gaps(self._complete(), []) == []

    def test_empty_quality_is_a_gap(self):
        assert [name for name, _ in summary_gaps(self._complete(calidad=[]), [])] == ["calidad"]

    def test_only_proposed_quality_is_a_gap(self):
        summary = self._complete(calidad_origen={"Seguridad": "propuesto"})
        assert [name for name, _ in summary_gaps(summary, [])] == ["calidad"]

    def test_missing_budget_in_the_summary_is_a_gap(self):
        summary = self._complete(restricciones=["Equipo de 3 personas", "Plazo de 3 meses"])
        assert [name for name, _ in summary_gaps(summary, [])] == ["presupuesto"]

    def test_a_category_already_asked_is_not_asked_again(self):
        question = summary_gaps(self._complete(calidad=[]), [])[0][1]
        history = [{"pregunta": question, "respuesta": "no sé"}]
        assert summary_gaps(self._complete(calidad=[]), history) == []



class TestArchitectureDrivers:
    """Plataforma, habilidades del equipo y fuente de los datos."""

    def _base(self):
        return [
            {"pregunta": "¿Quiénes usarán el sistema?", "respuesta": "Analistas."},
            {"pregunta": "¿Qué debe hacer?", "respuesta": "Consultar indicadores."},
            {"pregunta": "calidad", "respuesta": "Que sea rápido."},
            *_VIABLE_ANSWERS,
        ]

    def test_no_cierra_sin_saber_plataforma_habilidades_y_fuente_de_datos(self):
        missing = [name for name, _ in missing_coverage(self._base())]
        assert missing == ["plataforma", "habilidades", "fuente_datos"]

        model = _FakeModel(['{"done": true, "question": null, "reason": "listo"}'])
        decision = next_step(model, history=self._base())
        assert decision.done is False
        assert "navegador web" in decision.question
        assert not _es_pregunta_compuesta(decision.question)

    def test_las_respuestas_cubren_los_drivers(self):
        history = self._base() + [
            {"pregunta": "p", "respuesta": "Desde el navegador; sabemos React y Node."},
            {"pregunta": "p", "respuesta": "Los datos vienen de sensores en tiempo real."},
        ]
        assert missing_coverage(history) == []

    def test_las_preguntas_de_los_drivers_son_granulares(self):
        from app.core.elicitation_agent import _DRIVER_CATEGORIES

        for _name, _patterns, _asked, question in _DRIVER_CATEGORIES:
            assert question.count("?") == 1
            assert not _es_pregunta_compuesta(question)


class TestViabilityFacts:
    def test_conserva_las_palabras_del_usuario(self):
        from app.core.elicitation_agent import viability_facts

        team_question = _VIABILITY_FACTORS[1][2]
        history = [
            {"pregunta": team_question, "respuesta": "4 devs, 3 front y 1 PM"},
            {"pregunta": "p", "respuesta": "Tenemos 15000 USD. Entregamos en 4 meses."},
        ]
        facts = viability_facts(history)
        assert facts["equipo"] == "4 devs, 3 front y 1 PM"
        assert facts["presupuesto"] == "Tenemos 15000 USD."
        assert facts["plazo"] == "Entregamos en 4 meses."

    def test_el_resumen_lleva_los_datos_textuales(self):
        team_question = _VIABILITY_FACTORS[1][2]
        model = _FakeModel(
            ['{"problema": "x", "usuarios": "y", "funcionalidades": [], '
             '"restricciones": ["Equipo de 4"], "calidad": []}']
        )
        summary = generate_summary(
            model, history=[{"pregunta": team_question, "respuesta": "4 devs, 3 front y 1 PM"}]
        )
        assert summary["datos_viabilidad"] == {"equipo": "4 devs, 3 front y 1 PM"}

    def test_el_prompt_del_resumen_pide_no_reinterpretar_el_equipo(self):
        assert "3 front y 1 PM" in elicitation_agent.SUMMARY_SYSTEM_PROMPT
        assert '"contexto_tecnico"' in elicitation_agent.SUMMARY_SYSTEM_PROMPT
