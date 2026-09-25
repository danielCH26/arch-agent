"""Proposal API router.

Combines F08's proposal lifecycle endpoints with HU6's approved-proposal
snapshot contract used by diagram generation.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.dependencies import get_current_user
from app.api.projects import AVAILABLE_PHASES
from app.core.database import SessionLocal
from app.core.proposal_generator import ProposalGenerator, RAG_MIN_SIMILARITY
from app.core.session_store import record_approval_decision
from app.models import InteractionLog, Proposal, ProposalApproval
from app.models.approval import Approval
from app.models.message import Message
from app.models.project import Project
from app.models.session import UserSession

logger = logging.getLogger(__name__)

# Re-declared to avoid the circular import (see app/core/proposal_generator.py
# docstring + design.md section 9). MUST stay in sync with app/api/chat.py and
# app/core/proposal_generator.py until the rag_config refactor lands.
RAG_MIN_SIMILARITY = RAG_MIN_SIMILARITY

PROPOSAL_REJECT_REVERTS_TO = os.getenv("PROPOSAL_REJECT_REVERTS_TO", "requerimientos")
PROPOSAL_MAX_ITER = int(os.getenv("PROPOSAL_MAX_ITER", "5"))
PHASE = AVAILABLE_PHASES[1]  # "propuesta"
MAX_SNAPSHOT_CHARS = 20_000

router = APIRouter(tags=["proposals"])


class GenerateRequest(BaseModel):
    project_id: int = Field(..., description="Project to draft a proposal for")


class ModifyRequest(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=2000)


class DecideRequest(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    comment: Optional[str] = Field(None, max_length=2000)


class ProposalDecisionIn(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    feedback: Optional[str] = None
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


class ProposalOut(BaseModel):
    id: int
    project_id: int
    iteration: int
    content: str
    citations: list[dict]
    feedback: Optional[str]
    lifecycle: str
    created_at: str


def _emit_sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_stream(
    events: AsyncIterator[tuple[str, object]],
) -> AsyncIterator[str]:
    async for event, payload in events:
        yield _emit_sse(event, payload)


def _project_key(project_id: int) -> str:
    return str(project_id)


def _load_project_state(session_row: UserSession, project_id: int) -> tuple[dict, dict]:
    engram_state = dict(session_row.engram_state or {})
    raw = engram_state.get(_project_key(project_id))
    project_state = dict(raw) if isinstance(raw, dict) else {}
    return engram_state, project_state


def _latest_assistant_text(
    db: Session,
    *,
    session_id: int,
    project_id: int,
    user_id: int,
) -> str | None:
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


def _require_owned_project(db: Session, *, user_id: int, project_id: int) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )
    if project is not None:
        return project

    exists = db.query(Project).filter(Project.id == project_id).first()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este proyecto",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Proyecto no encontrado",
    )


def _content_to_text(content) -> str:
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if content is None:
        return ""
    return str(content)


def _apply_project_proposal_decision(
    db: Session,
    *,
    user_id: int,
    project: Project,
    decision: Literal["approve", "modify", "reject"],
    feedback: str | None,
    proposal_text: str | None,
) -> tuple[Approval, int, str]:
    """Persist the HU6 approval row and proposal snapshot for diagram grounding."""
    session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
    engram_state, project_state = (
        _load_project_state(session_row, int(project.id))
        if session_row is not None
        else ({}, {})
    )

    snapshot = (proposal_text or "").strip()
    if not snapshot and session_row is not None:
        snapshot = _latest_assistant_text(
            db,
            session_id=int(session_row.id),
            project_id=int(project.id),
            user_id=user_id,
        ) or ""

    if decision == "approve":
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No hay ninguna propuesta que aprobar en este proyecto. "
                    "Pedile la propuesta al asistente primero, o manda el "
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
        project_state.pop("propuesta", None)
        snapshot = ""
        message = (
            "Se registró tu solicitud de cambios sobre la propuesta."
            if decision == "modify"
            else "Propuesta rechazada."
        )

    approval = record_approval_decision(
        db,
        user_id=user_id,
        phase=PHASE,
        decision=decision,
        feedback=feedback,
        project_id=int(project.id),
    )
    if session_row is None:
        session_row = db.query(UserSession).filter(UserSession.id == approval.session_id).first()
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo resolver la sesión del usuario.",
        )

    project.phase_ready = decision == "approve"
    engram_state[_project_key(int(project.id))] = project_state
    session_row.engram_state = engram_state
    flag_modified(session_row, "engram_state")

    return approval, len(snapshot), message


@router.post("/api/proposals/generate")
async def generate_proposal(
    body: GenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    db = SessionLocal()
    try:
        _require_owned_project(db, user_id=user_id, project_id=body.project_id)
    finally:
        db.close()

    generator = ProposalGenerator(user_id=user_id, project_id=body.project_id)

    async def event_iterator():
        async for event, payload in generator.generate_stream(project_id=body.project_id):
            yield event, payload

    return StreamingResponse(
        _sse_stream(event_iterator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/proposals/{proposal_id}/modify")
async def modify_proposal(
    proposal_id: int,
    body: ModifyRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    db = SessionLocal()
    try:
        prior = db.get(Proposal, proposal_id)
        if prior is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        _require_owned_project(db, user_id=user_id, project_id=int(prior.project_id))
        if prior.lifecycle != "proposed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La propuesta ya está en estado '{prior.lifecycle}' "
                    "y no se puede modificar."
                ),
            )
        if prior.iteration >= PROPOSAL_MAX_ITER:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Has alcanzado el máximo de iteraciones ({PROPOSAL_MAX_ITER})",
            )
        project_id = int(prior.project_id)
    finally:
        db.close()

    generator = ProposalGenerator(user_id=user_id, project_id=project_id)

    async def event_iterator():
        async for event, payload in generator.generate_stream(
            project_id=project_id,
            feedback=body.feedback,
            prior_proposal_id=proposal_id,
        ):
            yield event, payload

    return StreamingResponse(
        _sse_stream(event_iterator()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/proposals/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: int,
    body: DecideRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    if body.decision == "modify":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Para modificar, usa POST /api/proposals/{id}/modify con "
                "{feedback} en el body."
            ),
        )

    db = SessionLocal()
    try:
        proposal = db.get(Proposal, proposal_id)
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        project = _require_owned_project(
            db,
            user_id=user_id,
            project_id=int(proposal.project_id),
        )
        if proposal.lifecycle != "proposed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La propuesta ya está en estado '{proposal.lifecycle}'.",
            )

        action_type = "approve" if body.decision == "approve" else "reject"
        existing = (
            db.query(InteractionLog)
            .filter(
                InteractionLog.project_id == proposal.project_id,
                InteractionLog.phase == PHASE,
                InteractionLog.action_type == action_type,
            )
            .order_by(InteractionLog.created_at.desc())
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta propuesta ya fue "
                    f"{'aprobada' if body.decision == 'approve' else 'rechazada'}."
                ),
            )

        if body.decision == "approve":
            proposal.lifecycle = "approved"
            decision_for_hu6: Literal["approve", "modify", "reject"] = "approve"
            db.add(
                ProposalApproval(
                    proposal_id=proposal_id,
                    decision="approved",
                    previous_output=proposal.content,
                )
            )
        else:
            proposal.lifecycle = "rejected"
            project.current_phase = PROPOSAL_REJECT_REVERTS_TO
            decision_for_hu6 = "reject"
            db.add(
                ProposalApproval(
                    proposal_id=proposal_id,
                    decision="rejected",
                    previous_output=proposal.content,
                )
            )

        db.add(
            InteractionLog(
                session_id=proposal.session_id,
                project_id=proposal.project_id,
                phase=PHASE,
                action_type=action_type,
                comment=body.comment,
            )
        )
        _apply_project_proposal_decision(
            db,
            user_id=user_id,
            project=project,
            decision=decision_for_hu6,
            feedback=body.comment,
            proposal_text=_content_to_text(proposal.content),
        )
        if body.decision == "approve":
            project.phase_ready = True
        else:
            project.phase_ready = False

        db.commit()
        db.refresh(proposal)
        db.refresh(project)

        return {
            "proposal_id": int(proposal.id),
            "lifecycle": proposal.lifecycle,
            "current_phase": project.current_phase,
            "phase_ready": bool(project.phase_ready),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("decide_proposal failed for proposal_id=%s", proposal_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo registrar la decisión: {exc}",
        ) from exc
    finally:
        db.close()


@router.get("/api/proposals/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: int,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    db = SessionLocal()
    try:
        proposal = db.get(Proposal, proposal_id)
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        _require_owned_project(db, user_id=user_id, project_id=int(proposal.project_id))
        created_at = proposal.created_at.isoformat() if proposal.created_at else ""

        return ProposalOut(
            id=int(proposal.id),
            project_id=int(proposal.project_id),
            iteration=int(proposal.iteration),
            content=_content_to_text(proposal.content),
            citations=list(proposal.citations or []),
            feedback=proposal.feedback,
            lifecycle=proposal.lifecycle,
            created_at=created_at,
        )
    finally:
        db.close()


@router.post("/api/projects/{project_id}/proposal/decision", response_model=ProposalDecisionOut)
async def decide_project_proposal(
    project_id: int,
    body: ProposalDecisionIn,
    current_user: dict = Depends(get_current_user),
):
    if body.decision == "modify" and not (body.feedback and body.feedback.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El feedback es obligatorio para 'modify'.",
        )

    user_id = int(current_user["user_id"])
    db = SessionLocal()
    try:
        project = _require_owned_project(db, user_id=user_id, project_id=project_id)
        approval, snapshot_chars, message = _apply_project_proposal_decision(
            db,
            user_id=user_id,
            project=project,
            decision=body.decision,
            feedback=body.feedback,
            proposal_text=body.proposal_text,
        )
        db.commit()
        db.refresh(approval)

        return ProposalDecisionOut(
            decision=body.decision,
            phase_ready=bool(project.phase_ready),
            approval_id=approval.id,
            proposal_snapshot_chars=snapshot_chars,
            message=message,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    finally:
        db.close()


@router.get("/api/projects/{project_id}/proposal", response_model=ProposalStateOut)
async def get_proposal_state(
    project_id: int,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["user_id"])

    db = SessionLocal()
    try:
        _require_owned_project(db, user_id=user_id, project_id=project_id)
        session_row = db.query(UserSession).filter(UserSession.user_id == user_id).first()
        if session_row is None:
            return ProposalStateOut(
                approved=False,
                approved_at=None,
                approval_id=None,
                proposal_snapshot_chars=0,
                last_decision=None,
            )

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
