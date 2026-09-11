from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user
from app.api.projects import AVAILABLE_PHASES, _require_project
from app.core import elicitation_agent
from app.core.database import SessionLocal
from app.core.llm_loader import build_langchain_model, LLMConfigError
from app.core.session_store import load_session_state, save_session_state
from app.models.approval import Approval
from app.models.project import Project
from app.models.session import UserSession

router = APIRouter(prefix="/api/projects", tags=["elicitation"])

# La elicitación es siempre la primera fase del flujo (ver AVAILABLE_PHASES
# en app/api/projects.py) -- se referencia por índice, no como string suelto,
# para no desalinearse si el orden de fases cambia.
PHASE = AVAILABLE_PHASES[0]  # "requerimientos"

DECISION_TO_DB = {
    "approve": "approved",
    "modify": "modified",
    "reject": "rejected",
}


# --- Pydantic models --------------------------------------------------------

class ElicitationMessageIn(BaseModel):
    # None (u omitido) en la primera llamada, o para volver a pedir la
    # pregunta pendiente sin gastar otra llamada al LLM.
    answer: Optional[str] = None


class ElicitationMessageOut(BaseModel):
    done: bool
    question: Optional[str]
    resumen: Optional[dict]
    history: list[dict]


class ElicitationDecisionIn(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None


class ElicitationDecisionOut(BaseModel):
    decision: str
    phase_ready: bool
    message: str


# --- Helpers -----------------------------------------------------------------
#
# BUG (encontrado en revisión de PR): `sessions` tiene una sola fila por
# usuario (UNIQUE en user_id, ver migration 0003), no una por proyecto. Si
# engram_state se indexa solo por fase ({"requerimientos": {...}}), dos
# proyectos distintos del mismo usuario comparten el mismo espacio y se
# pisan entre sí -- eso rompía reject/modify en la práctica (el estado que
# "reject" limpiaba, o "modify" reabría, no era el del proyecto correcto).
#
# Fix: anidar también por project_id dentro del mismo engram_state
# ({"3": {"requerimientos": {...}}, "5": {"requerimientos": {...}}}), sin
# tocar el esquema de `sessions` ni su semántica de "una sesión por
# usuario" -- ese cambio más profundo (una sesión por proyecto) queda como
# follow-up si hace falta, pero tiene mucho más blast radius (afecta
# session_store.py, chat.py, y las migraciones de `sessions`).

def _project_key(project_id: int) -> str:
    # Claves de dict en JSON siempre son string -- explícito para que quede
    # claro que no es un descuido, no porque project_id deje de ser int.
    return str(project_id)


def _phase_data_from_engram(engram_state: Optional[dict], project_id: int) -> dict:
    return (engram_state or {}).get(_project_key(project_id), {}).get(PHASE, {})


def _set_phase_data(engram_state: dict, project_id: int, phase_data: dict) -> dict:
    project_state = engram_state.setdefault(_project_key(project_id), {})
    project_state[PHASE] = phase_data
    return engram_state


# --- Routes --------------------------------------------------------------------

@router.get("/{project_id}/elicitation", response_model=ElicitationMessageOut)
async def get_elicitation_state(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """
    Estado actual de la elicitación para este proyecto: historial de
    preguntas/respuestas, la pregunta pendiente (si hay una) y el resumen
    (si el agente ya decidió que el contexto es suficiente).
    """
    _require_project(current_user["user_id"], project_id)

    state = load_session_state(current_user["user_id"]) or {}
    phase_data = _phase_data_from_engram(state.get("engram_state"), project_id)
    resumen = phase_data.get("resumen")

    return ElicitationMessageOut(
        done=resumen is not None,
        question=phase_data.get("pending_question"),
        resumen=resumen,
        history=phase_data.get("preguntas_respuestas", []),
    )


@router.post("/{project_id}/elicitation/message", response_model=ElicitationMessageOut)
async def send_elicitation_message(
    project_id: int,
    body: ElicitationMessageIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Responde la pregunta pendiente (si `answer` viene con contenido) y
    devuelve la siguiente pregunta progresiva, o el resumen si el agente
    decide que el contexto ya es suficiente (punto de decisión del issue).

    400 — no hay pregunta pendiente para responder, o ya existe un resumen
          (hay que pasar por /elicitation/decision antes de seguir)
    409 — LLM no configurado para este usuario
    502 — el modelo respondió pero con contenido no parseable
    503 — la llamada al modelo falló (rate limit, timeout, proveedor caído)
    """
    user_id = current_user["user_id"]
    project = _require_project(user_id, project_id)

    state = load_session_state(user_id) or {}
    engram_state = state.get("engram_state") or {}
    phase_data = _phase_data_from_engram(engram_state, project_id)

    if phase_data.get("resumen") is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya se generó el resumen de esta fase. Usa /elicitation/decision "
            "para aprobar, modificar o rechazar antes de seguir.",
        )

    history: list[dict] = phase_data.get("preguntas_respuestas", [])
    pending_question = phase_data.get("pending_question")

    if body.answer and body.answer.strip():
        if pending_question is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay una pregunta pendiente por responder todavía.",
            )
        history = history + [{"pregunta": pending_question, "respuesta": body.answer.strip()}]
        pending_question = None
    elif pending_question is not None:
        # Ya se había hecho esta pregunta y no llegó una respuesta nueva:
        # se re-devuelve tal cual, sin gastar otra llamada al LLM.
        return ElicitationMessageOut(
            done=False, question=pending_question, resumen=None, history=history
        )

    try:
        model = build_langchain_model(user_id)
    except LLMConfigError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="LLM no configurado. Ejecuta POST /api/llm/config primero.",
        )

    try:
        decision = elicitation_agent.next_step(model, history, project.description or "")
        if decision.done:
            resumen = elicitation_agent.generate_summary(model, history, project.description or "")
        else:
            resumen = None
    except elicitation_agent.ElicitationLLMError as e:
        # Falla real de la llamada (rate limit, timeout, proveedor caído) --
        # el usuario puede reintentar, no es un problema con lo que respondió.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"El modelo de IA no está disponible en este momento "
            f"(posible límite de tasa del proveedor). Intenta de nuevo en "
            f"unos segundos. Detalle: {e}",
        )
    except elicitation_agent.ElicitationAgentError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"El agente no pudo procesar la elicitación: {e}",
        )

    phase_data = {
        "preguntas_respuestas": history,
        "pending_question": None if decision.done else decision.question,
        "resumen": resumen,
    }
    engram_state = _set_phase_data(engram_state, project_id, phase_data)
    save_session_state(
        user_id, project_id=project.id, active_phase=PHASE, engram_state=engram_state
    )

    return ElicitationMessageOut(
        done=decision.done,
        question=phase_data["pending_question"],
        resumen=resumen,
        history=history,
    )


@router.post("/{project_id}/elicitation/decision", response_model=ElicitationDecisionOut)
async def decide_elicitation(
    project_id: int,
    body: ElicitationDecisionIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Aprueba, pide modificar o rechaza el resumen de elicitación generado.
    Escribe el historial de la decisión en `approvals` (criterio de
    aceptación del issue).

    - approve: marca phase_ready=True (ya puedes usar POST /advance)
    - modify:  agrega el feedback como contexto y reabre la elicitación
               (requiere `feedback`)
    - reject:  descarta todo el progreso de esta fase y reinicia desde cero
    """
    if body.decision == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El feedback es obligatorio para 'modify'.",
        )

    user_id = current_user["user_id"]
    _require_project(user_id, project_id)  # valida ownership antes de tocar la DB

    db = SessionLocal()
    try:
        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session_row is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No hay una sesión de elicitación activa para este proyecto.",
            )

        # Copia nueva del dict, no una referencia al mismo objeto que
        # session_row.engram_state -- ver nota de flag_modified() más abajo.
        engram_state = dict(session_row.engram_state or {})
        phase_data = _phase_data_from_engram(engram_state, project_id)
        if phase_data.get("resumen") is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Todavía no hay un resumen que aprobar, modificar o rechazar. "
                "Termina la elicitación con /elicitation/message primero.",
            )

        project = db.query(Project).filter(Project.id == project_id).first()

        db.add(
            Approval(
                session_id=session_row.id,
                phase=PHASE,
                decision=DECISION_TO_DB[body.decision],
                feedback=body.feedback,
            )
        )

        if body.decision == "approve":
            project.phase_ready = True
            message = "Elicitación aprobada. Ya puedes avanzar a la fase de propuesta."

        elif body.decision == "modify":
            history = phase_data.get("preguntas_respuestas", [])
            history = history + [
                {"pregunta": "(ajuste solicitado por el usuario)", "respuesta": body.feedback.strip()}
            ]
            engram_state = _set_phase_data(
                engram_state,
                project_id,
                {"preguntas_respuestas": history, "pending_question": None, "resumen": None},
            )
            session_row.engram_state = engram_state
            flag_modified(session_row, "engram_state")
            project.phase_ready = False
            message = "Se registró tu ajuste. Llama a /elicitation/message para continuar."

        else:  # reject
            engram_state = _set_phase_data(engram_state, project_id, {})
            session_row.engram_state = engram_state
            flag_modified(session_row, "engram_state")
            project.phase_ready = False
            message = "Elicitación rechazada. Se reinició esta fase, puedes empezar de nuevo."

        db.commit()
        return ElicitationDecisionOut(
            decision=body.decision, phase_ready=project.phase_ready, message=message
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        db.close()
