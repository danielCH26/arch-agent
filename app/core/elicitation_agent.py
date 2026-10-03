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
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

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
# sistema", "100 USD al mes"): el plazo exige una cantidad ("3 meses",
# "12 semanas") y el equipo se detecta por rol o por la palabra "equipo".
_NUMBER = r"(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce)"
_VIABILITY_FACTORS = (
    (
        "presupuesto",
        (
            r"presupuestos?", r"costos?", r"costes?", r"cop", r"usd",
            r"dolar(?:es)?", r"dinero", r"financ[a-z]*", r"inversion(?:es)?",
        ),
        "¿Con qué presupuesto cuentan para construir y operar el sistema? Si aún no está definido, indícame el rango o la restricción de gasto.",
    ),
    (
        "equipo",
        (
            r"equipos?", r"desarrolladores?", r"ingenier[oa]s?", r"programadores?",
            r"senior", r"junior", r"devops",
        ),
        "¿Cuántas personas integran el equipo y qué experiencia o roles técnicos tienen disponibles?",
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

# HU5: "El sistema inicia con pregunta abierta" -- se fuerza determinísticamente
# (no se le pide al LLM que decida la primera pregunta) para que este criterio
# de aceptación no dependa de que el modelo se porte bien.
FIRST_QUESTION = (
    "Para empezar, cuéntame en tus propias palabras: ¿qué problema quieres "
    "resolver con este sistema, y para quién es?"
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
        if _normalize_text(question).strip() not in asked_and_answered
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

    decision = ElicitationDecision(
        done=bool(data["done"]),
        question=data.get("question"),
        reason=data.get("reason", ""),
    )

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
            question=decision.question
            or "Cuéntame más sobre los requerimientos no funcionales "
            "(rendimiento, escalabilidad, seguridad) que tiene este proyecto.",
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
