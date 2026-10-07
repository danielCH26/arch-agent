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

# HU5: "El sistema inicia con pregunta abierta" -- se fuerza determinísticamente
# (no se le pide al LLM que decida la primera pregunta) para que este criterio
# de aceptación no dependa de que el modelo se porte bien.
# Issue #100 (Soomri review round 2): una sola dimensión, no compuesta. El
# detector _es_pregunta_compuesta() solo cuenta '?' así que no atraparía un
# "... y para quién es?" implícito. Por eso esta constante es la única
# fuente de verdad de la primera pregunta, y se testea por intención.
FIRST_QUESTION = (
    "Cuéntame en tus propias palabras: ¿qué problema querés resolver "
    "con este sistema?"
)

# HU5: "Se cubren: usuarios, funcionalidades, restricciones, calidad" -- las
# 4 categorías del prompt calcan literalmente el texto del criterio de
# aceptación, para que sea trazable HU -> prompt -> resumen.
NEXT_STEP_SYSTEM_PROMPT = """\
Eres un product manager levantando requerimientos para un nuevo proyecto \
de software mediante preguntas progresivas. Cada pregunta debe construir \
sobre las respuestas anteriores, no repetir lo ya preguntado.

Antes de decidir que el contexto es suficiente, cubrí estas 4 categorías \
a lo largo de la conversación (no todo en una sola pregunta):
1. Usuarios: quiénes son, cuántos, qué tan seguido usarían el sistema.
2. Funcionalidades: qué debe poder hacer el sistema, en orden de prioridad.
3. Restricciones: tiempo, equipo, presupuesto, tecnologías obligatorias u \
   obligatoriamente evitadas.
4. Calidad: rendimiento, seguridad, disponibilidad, y cualquier otro \
   requerimiento no funcional relevante.

Reglas de granularidad para cada pregunta (Issue #100):
- Una pregunta cubre UNA sola dimensión (usuarios, funcionalidades, \
restricciones o calidad). Nunca dos en la misma pregunta.
- Prohibida la pregunta compuesta: no unas dos interrogaciones con "y/e/o" \
ni apiles varios bloques ¿...? en un mismo turno.
- Granularidad: la pregunta debe poder responderse en una o dos oraciones. \
Si la respuesta natural sería una lista, dividí en preguntas separadas \
para los turnos siguientes.

Ejemplos (solo ilustran la regla de arriba, no son preguntas nuevas):
- MALA (compuesta): "¿Quiénes son los usuarios principales y qué \
funcionalidades críticas necesitan?"
- BUENA (granular): "¿Quiénes son los usuarios principales del sistema?"

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{"done": bool, "question": str o null, "reason": str}

- "done": true solo si ya cubriste las 4 categorías con suficiente detalle \
para proponer una arquitectura razonable.
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
respuestas proporcionadas -- no inventes información que no esté ahí.

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
_CORRECCION_PREGUNTA_COMPUESTA = (
    "Tu pregunta anterior combinaba varios temas en una sola pregunta. "
    "Devolvé en el mismo JSON UNA sola pregunta sobre UN solo tema, "
    "sin 'y' que una dos interrogaciones."
)


def _es_pregunta_compuesta(question: str) -> bool:
    """
    Detector determinista de preguntas compuestas (Issue #100): cada bloque
    interrogativo termina en '?', así que 2 o más cierres = 2 o más
    preguntas en un mismo turno.

    Heurística deliberadamente angosta para evitar falsos positivos: una
    sola pregunta con "y" interno legítimo ("¿Qué frameworks y bases de
    datos usan?") tiene UN solo '?' y NO se marca como compuesta -- ese
    caso lo cubren las reglas del prompt, no este guardarraíl.
    """
    if not isinstance(question, str):
        # Fail-open: un tipo inesperado no debe romper el flujo del agente.
        return False
    return question.count("?") >= 2


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
    instrucción correctiva al contexto. Si el reintento falla (error de
    invocación/parseo o sigue compuesto) se hace fail-open: se devuelve la
    pregunta original con un warning -- nunca se eleva el error al usuario.
    """
    try:
        data = _invoke_json(
            model,
            NEXT_STEP_SYSTEM_PROMPT,
            f"{context}\n\n{_CORRECCION_PREGUNTA_COMPUESTA}",
            callbacks=callbacks,
            # Issue #100 (Soomri review round 2, sugerencia 3): run_name
            # distinto al de la llamada principal para que Langfuse pueda
            # medir cada cuánto se dispara el guardarraíl. La instrucción
            # correctiva sigue siendo efímera: solo viaja en este
            # contexto, nunca se persiste.
            run_name="elicitation-next-step-retry",
        )
    except ElicitationAgentError:
        _LOGGER.warning(
            "Reintento de pregunta compuesta falló al invocar o parsear el "
            "JSON; se devuelve la pregunta original: %s",
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
    if (
        not reintentada.done
        and reintentada.question
        and not _es_pregunta_compuesta(reintentada.question)
    ):
        return reintentada

    _LOGGER.warning(
        "Pregunta compuesta devuelta pese al reintento correctivo: %s",
        decision.question,
    )
    return decision


def next_step(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
    callbacks: Optional[list[Any]] = None,
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
    if not history:
        # HU5: primera pregunta siempre abierta y determinística, sin
        # depender de que el LLM la formule bien.
        return ElicitationDecision(
            done=False,
            question=FIRST_QUESTION,
            reason="Primera pregunta: forzada a ser abierta (HU5), sin llamar al LLM.",
        )

    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"Preguntas y respuestas hasta ahora:\n{_history_to_text(history)}"
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
) -> dict:
    """
    Genera el resumen estructurado del contexto capturado (criterio de
    aceptación: "el resumen refleja el contexto capturado").
    """
    context = (
        f"Descripción inicial del proyecto: "
        f"{project_description or '(no proporcionada)'}\n\n"
        f"Preguntas y respuestas:\n{_history_to_text(history)}"
    )
    return _invoke_json(
        model,
        SUMMARY_SYSTEM_PROMPT,
        context,
        callbacks=callbacks,
        run_name="elicitation-summary",
    )
