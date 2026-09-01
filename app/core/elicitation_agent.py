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
from dataclasses import dataclass
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

# Reglas duras que NO dependen del LLM -- evitan que el agente "se rinda"
# demasiado pronto o se alargue indefinidamente, sin importar lo que
# decida el modelo.
MIN_QUESTIONS = 5
MAX_QUESTIONS = 10

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

Antes de decidir que el contexto es suficiente, cubre estas 4 categorías \
a lo largo de la conversación (no todo en una sola pregunta):
1. Usuarios: quiénes son, cuántos, qué tan seguido usarían el sistema.
2. Funcionalidades: qué debe poder hacer el sistema, en orden de prioridad.
3. Restricciones: tiempo, equipo, presupuesto, tecnologías obligatorias u \
   obligatoriamente evitadas.
4. Calidad: rendimiento, seguridad, disponibilidad, y cualquier otro \
   requerimiento no funcional relevante.

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


def _invoke_json(model: BaseChatModel, system_prompt: str, context: str) -> dict:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=context),
    ]
    response = model.invoke(messages)
    cleaned = _strip_json_fences(response.content)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ElicitationAgentError(
            f"El modelo no devolvió JSON válido: {e}. "
            f"Respuesta cruda: {response.content[:200]!r}"
        ) from e


def next_step(
    model: BaseChatModel,
    history: list[dict],
    project_description: str = "",
) -> ElicitationDecision:
    """
    Decide la siguiente pregunta progresiva, o si el contexto ya es
    suficiente (punto de decisión del issue: "¿Contexto suficiente?").

    Args:
        model: modelo LangChain ya construido (llm_loader.build_langchain_model)
        history: lista de {"pregunta": str, "respuesta": str} ya respondidas
        project_description: descripción inicial del proyecto, si existe

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

    data = _invoke_json(model, NEXT_STEP_SYSTEM_PROMPT, context)
    if "done" not in data:
        raise ElicitationAgentError(f"Falta la clave 'done' en la respuesta del modelo: {data}")

    decision = ElicitationDecision(
        done=bool(data["done"]),
        question=data.get("question"),
        reason=data.get("reason", ""),
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
    return _invoke_json(model, SUMMARY_SYSTEM_PROMPT, context)