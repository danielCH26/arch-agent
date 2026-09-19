"""
Decisión del usuario sobre la PROPUESTA de arquitectura (fase "propuesta").

Por qué existe este archivo (HU6):
    `app/api/chat.py::_load_approved_proposal_doc` busca en `approvals` una
    fila con `phase in {"propuesta", "proposal"}` y `decision == "approved"`
    para armar el documento sintético "PROPUESTA APROBADA PARA USAR COMO
    FUENTE DE VERDAD EN EL DIAGRAMA". Hoy NADIE escribe esa fila:
    `/api/projects/{id}/elicitation/decision` escribe phase="requerimientos"
    y `/api/diagrams/decision` escribe phase="diagram". Sin este endpoint el
    criterio de aceptación "el diagrama se basa en la propuesta aprobada"
    es inalcanzable: la función siempre retorna None.

Además del registro en `approvals`, al aprobar se guarda el TEXTO de la
propuesta en `sessions.engram_state[str(project_id)]["propuesta"]`, que es
la primera fuente que lee `_proposal_from_engram_state`. Sin ese snapshot,
`_load_approved_proposal_doc` cae al fallback "último mensaje del asistente
anterior a la aprobación", que es frágil: si el usuario escribió un mensaje
más después de la propuesta, el diagrama termina anclado al texto
equivocado.

Endpoints:
    POST /api/projects/{project_id}/proposal/decision
    GET  /api/projects/{project_id}/proposal
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user
from app.api.projects import AVAILABLE_PHASES, _require_project
from app.core.database import SessionLocal
from app.core.session_store import record_approval_decision
from app.models.approval import Approval
from app.models.message import Message
from app.models.project import Project
from app.models.session import UserSession

router = APIRouter(prefix="/api/projects", tags=["proposal"])

# Se referencia por índice y no como string suelto, igual que en
# elicitation.py, para no desalinearse si cambia el orden de fases.
PHASE = AVAILABLE_PHASES[1]  # "propuesta"

# Tope defensivo: el snapshot va dentro de un JSONB compartido con el
# estado de elicitación. Una propuesta larguísima (o un paste accidental)
# no debería inflar esa fila sin control ni reventar el context window del
# modelo cuando se inyecta como documento sintético.
MAX_SNAPSHOT_CHARS = 20_000


# --- Pydantic models ---------------------------------------------------------

class ProposalDecisionIn(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None
    # Opcional: el texto exacto de la propuesta que se está aprobando. Si no
    # viene, se toma el último mensaje del asistente de este proyecto.
    proposal_text: Optional[str] = None


class ProposalDecisionOut(BaseModel):
    decision: str
    phase_ready: bool
    approval_id: Optional[int]
    proposal_snapshot_chars: int
    message: str


class ProposalStateOut(BaseModel):
    approved: bool
    approved_at: Optional[str]
    approval_id: Optional[int]
    proposal_snapshot_chars: int
    last_decision: Optional[str]


# --- Helpers -----------------------------------------------------------------

def _project_key(project_id: int) -> str:
    # Las claves de un dict JSON siempre son string — explícito para que no
    # parezca un descuido. Mismo criterio que elicitation._project_key.
    return str(project_id)


def _latest_assistant_text(
    db,
    *,
    session_id: int,
    project_id: int,
    user_id: int,
) -> str | None:
    """Último mensaje del asistente de ESTE proyecto (no del último proyecto
    que el usuario tocó: `sessions` es una fila por usuario, ver el bug
    documentado en elicitation.py)."""
    row = (
        db.query(Message)
        .filter(
            Message.session_id == session_id,
            Message.project_id == project_id,
            Message.user_id == user_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )
    if row is None or not (row.content or "").strip():
        return None
    return row.content.strip()


def _load_project_state(session_row: UserSession, project_id: int) -> tuple[dict, dict]:
    """Devuelve (engram_state_copia, project_state_copia).

    Se trabaja siempre sobre copias nuevas: mutar el dict que ya está
    colgado del ORM no siempre dispara el UPDATE del JSONB (por eso el
    flag_modified de más abajo).
    """
    engram_state = dict(session_row.engram_state or {})
    raw = engram_state.get(_project_key(project_id))
    project_state = dict(raw) if isinstance(raw, dict) else {}
    return engram_state, project_state


# --- Routes ------------------------------------------------------------------

@router.post("/{project_id}/proposal/decision", response_model=ProposalDecisionOut)
async def decide_proposal(
    project_id: int,
    body: ProposalDecisionIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Aprueba, pide cambios o rechaza la propuesta de arquitectura.

    - approve: escribe Approval(phase="propuesta", decision="approved"),
               guarda el texto de la propuesta como fuente de verdad para el
               diagrama y marca phase_ready=True (habilita POST /advance).
    - modify:  registra el feedback (obligatorio) y borra el snapshot, para
               que el diagrama no se siga anclando a una propuesta que ya
               quedó obsoleta.
    - reject:  registra el rechazo y borra el snapshot.

    400 — 'modify' sin feedback, o 'approve' sin ningún texto de propuesta
          (ni en el body ni en el historial del chat)
    403/404 — proyecto de otro usuario / inexistente
    """
    if body.decision == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El feedback es obligatorio para 'modify'.",
        )

    user_id = current_user["user_id"]
    _require_project(user_id, project_id)  # ownership antes de tocar la DB

    db = SessionLocal()
    try:
        # record_approval_decision hace ensure_user_session por dentro: el
        # usuario puede llegar desde el chat sin haber pasado nunca por
        # /elicitation, y no tiene sentido bloquearlo por una fila de
        # bookkeeping. Pero OJO: la llamamos DESPUÉS de validar que haya
        # snapshot para 'approve' (más abajo) -- si la llamáramos antes,
        # el 400 de "no hay propuesta que aprobar" dejaría un `flush()`
        # sin commitear colgado en la sesión, dependiendo del rollback
        # del `except HTTPException` para no persistir nada. Validar
        # primero evita ese acoplamiento por completo.
        session_row = (
            db.query(UserSession).filter(UserSession.user_id == user_id).first()
        )
        project = (
            db.query(Project)
            .filter(Project.id == project_id, Project.user_id == user_id)
            .first()
        )

        engram_state, project_state = (
            _load_project_state(session_row, project_id)
            if session_row is not None
            else ({}, {})
        )

        snapshot = (body.proposal_text or "").strip()
        if not snapshot and session_row is not None:
            snapshot = _latest_assistant_text(
                db, session_id=session_row.id, project_id=project_id, user_id=user_id
            ) or ""

        if body.decision == "approve":
            if not snapshot:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "No hay ninguna propuesta que aprobar en este proyecto. "
                        "Pedile la propuesta al asistente primero, o mandá el "
                        "texto en 'proposal_text'."
                    ),
                )
            snapshot = snapshot[:MAX_SNAPSHOT_CHARS]
            project_state["propuesta"] = snapshot
            message = (
                "Propuesta aprobada. El diagrama va a usar este texto como "
                "fuente de verdad."
            )
        else:
            # modify / reject: la propuesta vigente deja de serlo. Si se
            # dejara el snapshot, _load_approved_proposal_doc lo seguiría
            # inyectando mientras exista CUALQUIER approval vieja aprobada.
            project_state.pop("propuesta", None)
            snapshot = ""
            message = (
                "Se registró tu solicitud de cambios sobre la propuesta."
                if body.decision == "modify"
                else "Propuesta rechazada."
            )

        # Ahora sí, con la validación ya pasada: registra la decisión
        # (crea la UserSession si todavía no existía).
        approval = record_approval_decision(
            db,
            user_id=user_id,
            phase=PHASE,
            decision=body.decision,
            feedback=body.feedback,
            project_id=project_id,
        )
        session_id = approval.session_id
        if session_row is None:
            session_row = db.query(UserSession).filter(UserSession.id == session_id).first()

        # Hallazgo #13 (revisión feature/hu6-diagrama): `project.phase_ready`
        # se asigna DESPUÉS de `record_approval_decision` (no antes). Esa
        # función llama a `ensure_user_session`, que ante una carrera de
        # `IntegrityError` en el INSERT hace `db.rollback()` -- si
        # `phase_ready` ya estuviera asignado en el objeto `project` tracked
        # por esta misma sesión, ese rollback lo descartaría en silencio.
        # Asignándolo después de que la sesión ya está garantizada, el
        # rollback (si ocurre) pasa antes de que haya nada más pendiente
        # que perder.
        project.phase_ready = body.decision == "approve"

        engram_state[_project_key(project_id)] = project_state
        session_row.engram_state = engram_state
        flag_modified(session_row, "engram_state")

        db.commit()
        db.refresh(approval)

        return ProposalDecisionOut(
            decision=body.decision,
            phase_ready=bool(project.phase_ready),
            approval_id=approval.id,
            proposal_snapshot_chars=len(snapshot),
            message=message,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
    finally:
        db.close()


@router.get("/{project_id}/proposal", response_model=ProposalStateOut)
async def get_proposal_state(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Estado de la propuesta de este proyecto.

    Sirve para QA y para que el front pueda decidir si muestra el botón de
    aprobar: dice si hay una aprobación vigente y si el snapshot de texto
    existe (si `approved=True` pero `proposal_snapshot_chars=0`, el diagrama
    va a caer al fallback por historial de chat).
    """
    user_id = current_user["user_id"]
    _require_project(user_id, project_id)

    db = SessionLocal()
    try:
        session_row = (
            db.query(UserSession).filter(UserSession.user_id == user_id).first()
        )
        if session_row is None:
            return ProposalStateOut(
                approved=False,
                approved_at=None,
                approval_id=None,
                proposal_snapshot_chars=0,
                last_decision=None,
            )

        # Migration 0016 / hallazgo #1: filtrar también por project_id, no
        # solo por session_id -- si no, GET /proposal de un proyecto B sin
        # ninguna aprobación devolvía approved=True porque el proyecto A
        # del mismo usuario sí tenía una.
        last = (
            db.query(Approval)
            .filter(
                Approval.session_id == session_row.id,
                Approval.project_id == project_id,
                Approval.phase == PHASE,
            )
            .order_by(Approval.created_at.desc(), Approval.id.desc())
            .first()
        )
        approved = last is not None and last.decision == "approved"

        _, project_state = _load_project_state(session_row, project_id)
        snapshot = project_state.get("propuesta") or ""

        return ProposalStateOut(
            approved=approved,
            approved_at=(
                last.created_at.isoformat()
                if approved and last.created_at is not None
                else None
            ),
            approval_id=last.id if approved else None,
            proposal_snapshot_chars=len(snapshot) if isinstance(snapshot, str) else 0,
            last_decision=last.decision if last is not None else None,
        )
    finally:
        db.close()