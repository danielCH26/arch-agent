"""
Lógica del agente de elicitación: preguntas progresivas, punto de decisión
(¿contexto suficiente?) y resumen del contexto capturado.

Issue: [F05] Elicitación guiada + aprobación

Recibe el modelo LangChain ya construido (build_langchain_model) en vez de
construirlo internamente, para poder testear next_step()/generate_summary()
con un modelo fake, sin necesitar credenciales ni red -- mismo criterio de
separación que ya usa model_classifier.py en este mismo paquete.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

_LOGGER = logging.getLogger(__name__)

# Reglas duras que NO dependen del LLM -- evitan que el agente "se rinda"
# demasiado pronto o se alargue indefinidamente, sin importar lo que
# decida el modelo.
MIN_QUESTIONS = 5
MAX_QUESTIONS = 10

# Estos tres datos no son una restricción genérica más: determinan si una
# propuesta es viable. Se buscan en las RESPUESTAS del usuario, en la
# descripción y en los documentos (nunca en el texto de las preguntas, que casi
# siempre nombran el tema aunque no se haya respondido) para no volver a
# preguntar lo ya conocido.
#
# Cada término es un fragmento de regex que se compara sobre texto sin acentos
# y en minúsculas, con límites de palabra (ver ``_factor_regex``): "mes" ya no
# coincide con "mesa" ni "cop" con "copia". Se evitan términos genéricos que
# aparecen en otros contextos ("tiempo de respuesta", "500 personas usarán el
# sistema", "100 USD al mes") y palabras del dominio del proyecto ("reducir
# costos de envío", "equipos de gimnasio"): el plazo exige una cantidad ("3
# meses", "12 semanas"), el presupuesto la palabra "presupuesto" o un monto
# ("5000usd", "$20.000", "10 mil pesos") y el equipo la palabra "equipo" en
# singular, un conteo ("somos 3", "3 desarrolladores") o un rol con seniority.
_NUMBER = r"(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce)"
_MONEY_AMOUNT = r"\d[\d.,]*(?:\s*(?:k|mil|millones?))?"
_DEV_ROLE = r"(?:desarrollador(?:es)?|programador(?:es)?|developers?|devs?|ingenier[oa]s?\s+de\s+software)"
_VIABILITY_FACTORS = (
    (
        "presupuesto",
        (
            r"presupuestos?",
            # monto + moneda, sin exigir espacio: "5000usd", "20000cop", "10 mil pesos"
            _MONEY_AMOUNT + r"\s*(?:de\s+)?(?:usd|cop|dolar(?:es)?|pesos?)",
            # moneda + monto: "USD 5000", "$20.000"
            r"(?:usd|cop|us\$)\s*" + _MONEY_AMOUNT,
            r"\$\s*" + _MONEY_AMOUNT,
            r"inversion\s+(?:inicial|maxima|total|disponible|limitada)",
        ),
        "¿Con qué presupuesto cuentan para construir y operar el sistema? Si aún no está definido, indícame el rango o la restricción de gasto.",
    ),
    (
        "equipo",
        (
            r"equipo",
            r"somos\s+" + _NUMBER,
            _NUMBER + r"\s+(?:\w+\s+)?" + _DEV_ROLE,
            _DEV_ROLE + r"\s+(?:senior|junior|semi\s*senior)",
            r"unipersonal",
            r"devops",
        ),
        # Issue #100: un solo aspecto. Antes era "¿Cuántas personas ... y qué
        # experiencia o roles ...?", una pregunta compuesta que además salta el
        # guardarraíl (las preguntas de viabilidad se devuelven sin pasar por
        # el LLM). Los roles se pueden preguntar en un turno posterior.
        "¿Cuántas personas integran el equipo de desarrollo?",
    ),
    (
        "plazo",
        (
            r"plazos?", r"deadline", r"fecha(?:s)?\s+(?:limite|de\s+entrega)",
            r"entrega", r"calendario", r"mvp",
            _NUMBER + r"\s*(?:mes(?:es)?|semanas?|dias?|trimestres?|anos?)",
        ),
        "¿Cuál es el plazo objetivo para el MVP o la primera entrega utilizable?",
    ),
)

# Pregunta de respaldo cuando el modelo quiere cerrar antes del mínimo y no
# devolvió ninguna pregunta. Constante (no literal en next_step) para que el
# test de registro la cubra.
MIN_QUESTIONS_FALLBACK = (
    "Cuéntame más sobre los requerimientos no funcionales "
    "(rendimiento, escalabilidad, seguridad) que tiene este proyecto."
)

# HU5: "El sistema inicia con pregunta abierta" -- se fuerza determinísticamente
# (no se le pide al LLM que decida la primera pregunta) para que este criterio
# de aceptación no dependa de que el modelo se porte bien.
# Issue #100: una sola dimensión, no compuesta. Esta pregunta no pasa por
# el guardarraíl _es_pregunta_compuesta() (next_step retorna antes de
# invocar al LLM), y el detector tampoco atraparía un "para quién es"
# implícito. Por eso esta constante es la única fuente de verdad de la
# primera pregunta, y se testea por intención.
# Registro: tuteo, igual que el resto del producto (frontend y prompts).
FIRST_QUESTION = (
    "Cuéntame en tus propias palabras: ¿qué problema quieres resolver "
    "con este sistema?"
)

# HU5: "Se cubren: usuarios, funcionalidades, restricciones, calidad" -- las
# 4 categorías del prompt calcan literalmente el texto del criterio de
# aceptación, para que sea trazable HU -> prompt -> resumen.
NEXT_STEP_SYSTEM_PROMPT = """\
Eres un product manager levantando requerimientos para un nuevo proyecto \
de software mediante preguntas progresivas. Cada pregunta debe construir \
sobre las respuestas anteriores, no repetir lo ya preguntado.

Cuando recibas documentos del proyecto, evalúa primero si cada dato es
relevante para la descripción del proyecto y las respuestas del usuario.
Usa únicamente los datos que describan el problema, usuarios, alcance,
funcionalidades, restricciones o calidad del proyecto. Ignora contenido
ajeno al proyecto. Los hechos relevantes de los documentos ya son contexto
conocido: no los vuelvas a preguntar; formula preguntas solo sobre vacíos,
ambigüedades o contradicciones que impidan definir la arquitectura.

Antes de decidir que el contexto es suficiente, cubre estas 4 categorías \
a lo largo de la conversación (no todo en una sola pregunta):
1. Usuarios: quiénes son, cuántos, qué tan seguido usarían el sistema.
2. Funcionalidades: qué debe poder hacer el sistema, en orden de prioridad.
3. Restricciones: tiempo, equipo, presupuesto, tecnologías obligatorias u \
   obligatoriamente evitadas. Presupuesto, tamaño/capacidad del equipo y \
   plazo son factores de viabilidad obligatorios: confirma los tres con \
   datos concretos o con la indicación explícita de que aún no se definieron.
4. Calidad: rendimiento, seguridad, disponibilidad, y cualquier otro \
   requerimiento no funcional relevante.

Reglas de granularidad para cada pregunta (Issue #100):
- Una pregunta cubre UNA sola dimensión (usuarios, funcionalidades, \
restricciones o calidad). Nunca dos en la misma pregunta. Dentro de una \
dimensión, pregunta por un solo aspecto a la vez (por ejemplo, quiénes \
son los usuarios; cuántos serían, en otra pregunta).
- Prohibida la pregunta compuesta: no unas dos interrogaciones con "y/e/o" \
ni apiles varios bloques ¿...? en un mismo turno.
- Granularidad: la pregunta debe poder responderse en una o dos oraciones. \
Si la respuesta natural sería una lista, divide en preguntas separadas \
para los turnos siguientes.

Ejemplos (solo ilustran la regla de arriba, no son preguntas nuevas):
- MALA (compuesta): "¿Quiénes son los usuarios principales y qué \
funcionalidades críticas necesitan?"
- BUENA (granular): "¿Quiénes son los usuarios principales del sistema?"

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{"done": bool, "question": str o null, "reason": str}

- "done": true solo si ya cubriste las 4 categorías con suficiente detalle \
para proponer una arquitectura razonable y conoces presupuesto, equipo y \
plazo (desde respuestas o documentos relevantes).
- "question": la siguiente pregunta a hacer (null si done=true).
- "reason": una frase corta explicando la decisión (para logs, no se \
muestra al usuario).
"""

# HU5: "El resumen final es completo y validable" -- las claves calcan las
# 4 categorías de arriba (mismo criterio de trazabilidad), y cada una es un
# campo discreto que un product manager puede revisar y marcar como
# cubierto o no, en vez de un párrafo suelto.
SUMMARY_SYSTEM_PROMPT = """\
Eres un product manager resumiendo los requerimientos levantados durante \
una sesión de elicitación. Basado ÚNICAMENTE en las preguntas y \
respuestas proporcionadas y, si existen, en los documentos aportados por el \
usuario -- no inventes información que no esté ahí. Antes de usar un dato de \
un documento, verifica que sea relevante para el problema y alcance del \
proyecto; ignora contenido ajeno. Si un documento relevante contradice una \
respuesta anterior, prioriza el documento (es más reciente).

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{
  "problema": str,
  "usuarios": str,
  "funcionalidades": [str, ...],
  "restricciones": [str, ...],
  "calidad": [str, ...]
}
"""


class ElicitationAgentError(Exception):
    """El LLM no devolvió una respuesta parseable como espera este módulo."""


class ElicitationLLMError(ElicitationAgentError):
    """
    La llamada al LLM en sí falló (rate limit, timeout, error de red o del
    proveedor) -- distinto de que el LLM haya respondido pero con un
    contenido no parseable. Encontrado en pruebas: Groq devuelve 429 al
    superar el límite de tokens por minuto, y eso se propagaba como un 500
    crudo antes de este fix.
    """


@dataclass
class ElicitationDecision:
    done: bool
    question: Optional[str]
    reason: str


# Instrucción correctiva efímera del reintento (Issue #100): solo viaja en
# el contexto de ESTA llamada -- nunca se persiste en historial ni estado.
# Incluye la pregunta rechazada: sin ella el modelo tendría que adivinar
# qué corregir y, con temperatura baja, tendería a repetirla.
_CORRECCION_PREGUNTA_COMPUESTA = (
    "Tu pregunta anterior combinaba varios temas en una sola pregunta: "
    "\"{pregunta_rechazada}\". "
    "Devuelve en el mismo JSON UNA sola pregunta sobre UN solo tema, "
    "sin 'y' que una dos interrogaciones."
)


# Palabras interrogativas (con tilde) que abren una segunda pregunta tras un
# conector. Se exige la tilde a propósito: sin ella "que", "como", "cuando"
# o "donde" son conjunciones/relativos muy comunes ("... y como
# administradores", "... o cuando sea posible") y darían falsos positivos.
_INTERROG = (
    r"(?:(?:por|para|a|con)\s+)?"
    r"(?:qué|quién(?:es)?|cuál(?:es)?|cuánt[oa]s?|cómo|cuándo|dónde)"
)
_CONECTOR_INTERROG = re.compile(rf"\b(?:y|e|o)\s+{_INTERROG}\b", re.IGNORECASE)


def _es_pregunta_compuesta(question: str) -> bool:
    """
    Detector determinista de preguntas compuestas (Issue #100). Marca como
    compuesta una pregunta que:

    1. Tiene 2 o más cierres '?': cada bloque interrogativo termina en '?',
       así que 2 o más cierres = 2 o más preguntas apiladas en un turno.
    2. Une dos interrogaciones con un conector y/e/o seguido de una palabra
       interrogativa, aunque haya un solo '?' ("¿Quiénes son los usuarios y
       qué funcionalidades necesitan?").

    Heurística deliberadamente angosta para evitar falsos positivos: una
    sola pregunta con "y" interno legítimo entre sustantivos ("¿Qué
    frameworks y bases de datos usan?") NO se marca -- "y bases" no es "y"
    + palabra interrogativa. Ese caso lo cubren las reglas del prompt.
    """
    if not isinstance(question, str):
        # Fail-open: un tipo inesperado no debe romper el flujo del agente.
        return False
    return question.count("?") >= 2 or bool(_CONECTOR_INTERROG.search(question))


def _history_to_text(history: list[dict]) -> str:
    if not history:
        return "(sin preguntas respondidas todavía)"
    lines = []
    for i, qa in enumerate(history, start=1):
        lines.append(f"{i}. P: {qa['pregunta']}\n   R: {qa['respuesta']}")
    return "\n".join(lines)


def _strip_json_fences(raw_content: str) -> str:
    """Tolera que el modelo envuelva el JSON en ```json ... ``` pese al prompt."""
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def _extract_json_object(text: str) -> str:
    """
    Extrae el primer objeto JSON completo del texto (del primer '{' al
    último '}'), ignorando cualquier razonamiento visible que algunos
    modelos anteponen (ej. bloques <think>...</think> de modelos con
    razonamiento, como qwen3 vía Groq -- encontrado en revisión de PR).
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    return text[start : end + 1]


def _invoke_json(
    model: BaseChatModel,
    system_prompt: str,
    context: str,
    callbacks: Optional[list[Any]] = None,
    run_name: Optional[str] = None,
) -> dict:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context),
    ]
    try:
        if callbacks:
            # F14: con callbacks (ej. Langfuse) la llamada queda trazada.
            # run_name distingue estas trazas de las del chat en la UI.
            config: dict[str, Any] = {"callbacks": callbacks}
            if run_name:
                config["run_name"] = run_name
            response = model.invoke(messages, config=config)
        else:
            response = model.invoke(messages)
    except Exception as e:
        # Cualquier falla real de la llamada (429 rate limit, timeout, error
        # de red o del proveedor) -- no solo errores de parseo de JSON.
        raise ElicitationLLMError(f"La llamada al modelo falló: {e}") from e

    cleaned = _strip_json_fences(response.content)
    cleaned = _extract_json_object(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ElicitationAgentError(
            f"El modelo no devolvió JSON válido: {e}. "
            f"Respuesta cruda: {response.content[:200]!r}"
        ) from e


def _decision_from_data(data: dict) -> ElicitationDecision:
    return ElicitationDecision(
        done=bool(data["done"]),
        question=data.get("question"),
        reason=data.get("reason", ""),
    )


def _reintentar_pregunta_granular(
    model: BaseChatModel,
    decision: ElicitationDecision,
    context: str,
    callbacks: Optional[list[Any]],
) -> ElicitationDecision:
    """
    Guardarraíl determinista (Issue #100): si la pregunta del modelo es
    evidentemente compuesta, se reintenta UNA sola vez agregando una
    instrucción correctiva (que incluye la pregunta rechazada) al contexto.

    Fail-open total: ante CUALQUIER falla del reintento (error de
    invocación o de parseo, JSON que no es un objeto, contenido con una
    forma inesperada, o una pregunta inválida o todavía compuesta) se
    devuelve la pregunta original con un warning -- nunca se eleva un
    error al usuario.
    """
    correccion = _CORRECCION_PREGUNTA_COMPUESTA.format(
        pregunta_rechazada=decision.question
    )
    try:
        data = _invoke_json(
            model,
            NEXT_STEP_SYSTEM_PROMPT,
            f"{context}\n\n{correccion}",
            callbacks=callbacks,
            # run_name distinto al de la llamada principal para que Langfuse
            # pueda medir cada cuánto se dispara el guardarraíl. La
            # instrucción correctiva sigue siendo efímera: solo viaja en
            # este contexto, nunca se persiste.
            run_name="elicitation-next-step-retry",
        )
    except Exception as e:  # noqa: BLE001 -- fail-open: nada debe llegar al usuario
        _LOGGER.warning(
            "Reintento de pregunta compuesta falló al invocar o parsear la "
            "respuesta (%s: %s); se devuelve la pregunta original: %s",
            type(e).__name__,
            e,
            decision.question,
        )
        return decision

    if not isinstance(data, dict):
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió un JSON que no es un "
            "objeto (%s); se devuelve la pregunta original: %s",
            type(data).__name__,
            decision.question,
        )
        return decision

    if "done" not in data:
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió un JSON sin la clave "
            "'done'; se devuelve la pregunta original: %s",
            decision.question,
        )
        return decision

    reintentada = _decision_from_data(data)
    if reintentada.done:
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió done=true; se "
            "devuelve la pregunta original: %s",
            decision.question,
        )
        return decision

    nueva = reintentada.question
    if not isinstance(nueva, str) or not nueva.strip():
        _LOGGER.warning(
            "Reintento de pregunta compuesta devolvió una pregunta vacía o "
            "que no es texto (%s); se devuelve la pregunta original: %s",
            type(nueva).__name__,
            decision.question,
        )
        return decision

    if _es_pregunta_compuesta(nueva):
        _LOGGER.warning(
            "Pregunta compuesta devuelta pese al reintento correctivo: %s",
            decision.question,
        )
        return decision

    return reintentada


def _documents_section(documents_context: Optional[str]) -> str:
    if not documents_context or not documents_context.strip():
        return ""
    return (
        "\n\nDocumentos aportados por el usuario (actas, notas, "
        "especificaciones). Evalúa su relevancia para este proyecto antes de "
        "usarlos; los datos relevantes ya son información conocida y no debes "
        f"volver a preguntarlos:\n{documents_context.strip()}"
    )


def _normalize_text(text: Optional[str]) -> str:
    """Minúsculas y sin acentos, para comparar texto libre.

    Misma normalización que ``proposal_generator._normalize_text``; se repite
    aquí para no importar ese módulo (y su acceso a base de datos) desde el
    agente de elicitación.
    """
    return "".join(
        char
        for char in unicodedata.normalize("NFD", (text or "").casefold())
        if unicodedata.category(char) != "Mn"
    )


def _factor_regex(patterns: tuple[str, ...]) -> "re.Pattern[str]":
    """Regex con límites de palabra que no cuentan dígitos a la izquierda."""
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(patterns) + r")(?![a-z])")


# Textos anteriores de las preguntas de viabilidad. Una sesión que ya respondió
# la versión vieja (antes del deploy que la cambió) no debe recibir la nueva
# otra vez solo porque el texto no coincide: el reconocimiento por "pregunta ya
# hecha" compara el texto exacto, y la respuesta puede no matchear la regex
# (p. ej. "3 personas, 2 backend").
_LEGACY_VIABILITY_QUESTIONS: dict[str, tuple[str, ...]] = {
    "equipo": (
        "¿Cuántas personas integran el equipo y qué experiencia o roles "
        "técnicos tienen disponibles?",
    ),
}


_VIABILITY_REGEXES = {
    name: _factor_regex(patterns) for name, patterns, _question in _VIABILITY_FACTORS
}


def _missing_viability_factors(
    history: list[dict],
    project_description: str,
    documents_context: Optional[str],
) -> list[tuple[str, str]]:
    """Return feasibility inputs absent from all available project context.

    Solo cuentan las respuestas del usuario, la descripción y los documentos.
    Si el agente ya hizo la pregunta de viabilidad de un factor y el usuario
    respondió (aunque sea "aún no está definido"), el factor se da por
    cubierto: así no se repite la misma pregunta en cada turno.
    """
    answers_text = "\n".join(str(item.get("respuesta") or "") for item in history)
    context = _normalize_text(
        " ".join(
            part
            for part in (project_description, documents_context or "", answers_text)
            if part
        )
    )
    asked_and_answered = {
        _normalize_text(str(item.get("pregunta") or "")).strip()
        for item in history
        if str(item.get("respuesta") or "").strip()
    }
    return [
        (name, question)
        for name, _patterns, question in _VIABILITY_FACTORS
        if not any(
            _normalize_text(text).strip() in asked_and_answered
            for text in (question, *_LEGACY_VIABILITY_QUESTIONS.get(name, ()))
        )
        and not _VIABILITY_REGEXES[name].search(context)
    ]


def next_step(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
    callbacks: Optional[list[Any]] = None,
    documents_context: Optional[str] = None,
) -> ElicitationDecision:
    """
    Decide la siguiente pregunta progresiva, o si el contexto ya es
    suficiente (punto de decisión del issue: "¿Contexto suficiente?").

    Args:
        model: modelo LangChain ya construido (llm_loader.build_langchain_model)
        history: lista de {"pregunta": str, "respuesta": str} ya respondidas
        project_description: descripción inicial del proyecto, si existe
        callbacks: handlers de LangChain opcionales (ej. Langfuse, F14)

    Returns:
        ElicitationDecision(done, question, reason)
    """
    if not history and not documents_context:
        # HU5: primera pregunta siempre abierta y determinística, sin
        # depender de que el LLM la formule bien. Si hay documentos, se usa
        # el modelo para que la primera pregunta cubra únicamente vacíos
        # reales del contexto disponible.
        return ElicitationDecision(
            done=False,
            question=FIRST_QUESTION,
            reason="Primera pregunta: forzada a ser abierta (HU5), sin llamar al LLM.",
        )

    initial_context = (
        "No hay respuestas todavía. Formula una primera pregunta abierta que "
        "parta de los documentos relevantes y pida solo la información que "
        "falte para entender el problema y sus usuarios."
        if not history
        else f"Preguntas y respuestas hasta ahora:\n{_history_to_text(history)}"
    )
    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"{initial_context}"
        f"{_documents_section(documents_context)}"
    )

    data = _invoke_json(
        model,
        NEXT_STEP_SYSTEM_PROMPT,
        context,
        callbacks=callbacks,
        run_name="elicitation-next-step",
    )
    if "done" not in data:
        raise ElicitationAgentError(f"Falta la clave 'done' en la respuesta del modelo: {data}")

    decision = _decision_from_data(data)

    # Regla dura complementaria al prompt: el LLM no puede cerrar ni saltarse
    # los límites que condicionan coste, complejidad y entrega. Solo se aplica
    # cuando el modelo quiere cerrar (done) o ya pasó el mínimo de preguntas:
    # antes corría en cada turno y, desde la segunda, pisaba la pregunta del
    # LLM (ya pagada) con las de presupuesto, equipo y plazo, rompiendo la
    # progresión de HU5. Y respeta MAX_QUESTIONS: a partir del máximo no se
    # hace una pregunta más, se cierra (ver abajo).
    if len(history) < MAX_QUESTIONS and (
        decision.done or len(history) >= MIN_QUESTIONS
    ):
        missing_viability = _missing_viability_factors(
            history, project_description, documents_context
        )
        if missing_viability:
            factor, question = missing_viability[0]
            return ElicitationDecision(
                done=False,
                question=question,
                reason=f"Falta el factor de viabilidad obligatorio: {factor}.",
            )

    if len(history) < MIN_QUESTIONS and decision.done:
        # Regla dura: no se puede terminar antes del mínimo, sin importar
        # lo que diga el modelo.
        decision = ElicitationDecision(
            done=False,
            question=decision.question or MIN_QUESTIONS_FALLBACK,
            reason="Forzado: aún no se alcanza el mínimo de preguntas "
            f"({len(history)}/{MIN_QUESTIONS}).",
        )
    elif len(history) >= MAX_QUESTIONS and not decision.done:
        # Regla dura opuesta: no dejar que se alargue indefinidamente.
        decision = ElicitationDecision(
            done=True,
            question=None,
            reason=f"Forzado: se alcanzó el máximo de preguntas ({MAX_QUESTIONS}).",
        )

    if (
        not decision.done
        and decision.question
        and _es_pregunta_compuesta(decision.question)
    ):
        # Issue #100: guardarraíl determinista contra preguntas compuestas.
        # Va después de las reglas duras para no gastar un reintento en una
        # pregunta que igual sería descartada (ej. máximo alcanzado).
        decision = _reintentar_pregunta_granular(model, decision, context, callbacks)

    return decision


def generate_summary(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
    callbacks: Optional[list[Any]] = None,
    documents_context: Optional[str] = None,
) -> dict:
    """
    Genera el resumen estructurado del contexto capturado (criterio de
    aceptación: "el resumen refleja el contexto capturado").
    """
    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"Preguntas y respuestas:\n{_history_to_text(history)}"
        f"{_documents_section(documents_context)}"
    )
    return _invoke_json(
        model,
        SUMMARY_SYSTEM_PROMPT,
        context,
        callbacks=callbacks,
        run_name="elicitation-summary",
    )
