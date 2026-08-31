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

NEXT_STEP_SYSTEM_PROMPT = """\
Eres un arquitecto de software levantando requerimientos para un nuevo \
proyecto mediante preguntas progresivas. Cada pregunta debe construir \
sobre las respuestas anteriores, no repetir lo ya preguntado.

Cubre, a lo largo de la conversación (no todo en una sola pregunta):
- Qué problema resuelve el sistema y para quién
- Usuarios esperados y escala (cuántos, concurrencia)
- Requerimientos no funcionales relevantes (rendimiento, seguridad, \
disponibilidad)
- Restricciones de tiempo, equipo o presupuesto
- Cualquier integración o dependencia externa relevante

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{"done": bool, "question": str o null, "reason": str}

- "done": true solo si ya tienes contexto suficiente para proponer una \
arquitectura razonable.
- "question": la siguiente pregunta a hacer (null si done=true).
- "reason": una frase corta explicando la decisión (para logs, no se \
muestra al usuario).
"""

SUMMARY_SYSTEM_PROMPT = """\
Eres un arquitecto de software resumiendo los requerimientos levantados \
durante una sesión de elicitación. Basado ÚNICAMENTE en las preguntas y \
respuestas proporcionadas -- no inventes información que no esté ahí.

Responde SIEMPRE en JSON, sin texto adicional antes o después, con esta \
forma exacta:
{
  "problema": str,
  "usuarios_y_escala": str,
  "requerimientos_funcionales": [str, ...],
  "requerimientos_no_funcionales": [str, ...],
  "restricciones": [str, ...]
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
