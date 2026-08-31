"""
Endpoints CRUD de propuestas (F08).

Issue: #12

Seguridad (R5): ownership verificado vía proposal → session → user.
Sin acceso → 404 (nunca 403) para evitar information leak.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.models.proposal import Proposal, Approval
from app.models.session import UserSession

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


# --- Pydantic models ----------------------------------------------------------


class ProposalOut(BaseModel):
    id: int
    session_id: int
    phase: str
    version: int
    content: Dict[str, Any]
    status: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class FeedbackIn(BaseModel):
    feedback: str


class ApprovalOut(BaseModel):
    id: int
    proposal_id: int
    decision: str
    feedback: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


# --- Helpers -------------------------------------------------------------------


def _get_owned_proposal(proposal_id: int, user_id: int) -> Proposal:
    """
    Carga la propuesta verificando ownership vía session → user.

    R5: retorna 404 (no 403) cuando no hay acceso para evitar information leak.
    """
    db = SessionLocal()
    try:
        proposal = (
            db.query(Proposal)
            .join(UserSession, Proposal.session_id == UserSession.id)
            .filter(
                Proposal.id == proposal_id,
                UserSession.user_id == user_id,
            )
            .first()
        )
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        return proposal
    finally:
        db.close()


def _record_approval(
    proposal_id: int,
    decision: str,
    feedback: Optional[str] = None,
    previous_content: Optional[Dict[str, Any]] = None,
    modified_content: Optional[Dict[str, Any]] = None,
) -> Approval:
    """Crea un registro de approval."""
    db = SessionLocal()
    try:
        approval = Approval(
            proposal_id=proposal_id,
            decision=decision,
            feedback=feedback,
            previous_content=previous_content,
            modified_content=modified_content,
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        return approval
    finally:
        db.close()


def _set_status(proposal_id: int, new_status: str) -> None:
    """Actualiza el status de la propuesta."""
    db = SessionLocal()
    try:
        proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
        if proposal:
            proposal.status = new_status
            db.commit()
    finally:
        db.close()


# --- Endpoints -------------------------------------------------------------------


@router.get("")
async def list_proposals(
    session_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Lista las propuestas de una sesión (propias únicamente)."""
    user_id = current_user["user_id"]

    db = SessionLocal()
    try:
        # Verificar que la sesión pertenece al user (privacidad)
        session = (
            db.query(UserSession)
            .filter(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            # 404 sin detalles: no revelamos si la sesión existe de otro user
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sesión no encontrada",
            )

        proposals = (
            db.query(Proposal)
            .filter(Proposal.session_id == session_id)
            .order_by(Proposal.version.desc())
            .all()
        )
        return [
            ProposalOut(
                id=p.id,
                session_id=p.session_id,
                phase=p.phase,
                version=p.version,
                content=p.content,
                status=p.status,
                created_at=p.created_at.isoformat() if p.created_at else None,
            )
            for p in proposals
        ]
    finally:
        db.close()


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Detalle de una propuesta (propias únicamente)."""
    proposal = _get_owned_proposal(proposal_id, current_user["user_id"])
    return ProposalOut(
        id=proposal.id,
        session_id=proposal.session_id,
        phase=proposal.phase,
        version=proposal.version,
        content=proposal.content,
        status=proposal.status,
        created_at=proposal.created_at.isoformat() if proposal.created_at else None,
    )


@router.post("/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Aprueba la propuesta: status → approved + registra la decisión."""
    proposal = _get_owned_proposal(proposal_id, current_user["user_id"])

    if proposal.status == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La propuesta ya está aprobada",
        )

    _set_status(proposal_id, "approved")
    approval = _record_approval(
        proposal_id=proposal_id,
        decision="approved",
        previous_content=proposal.content,
    )
    return ApprovalOut(
        id=approval.id,
        proposal_id=approval.proposal_id,
        decision=approval.decision,
        feedback=approval.feedback,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
    )


@router.post("/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    body: FeedbackIn,
    current_user: dict = Depends(get_current_user),
):
    """Rechaza la propuesta con feedback: status → rejected + registra la decisión."""
    proposal = _get_owned_proposal(proposal_id, current_user["user_id"])

    if proposal.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La propuesta ya está rechazada",
        )

    _set_status(proposal_id, "rejected")
    approval = _record_approval(
        proposal_id=proposal_id,
        decision="rejected",
        feedback=body.feedback,
        previous_content=proposal.content,
    )
    return ApprovalOut(
        id=approval.id,
        proposal_id=approval.proposal_id,
        decision=approval.decision,
        feedback=approval.feedback,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
    )


@router.post("/{proposal_id}/modify")
async def modify_proposal(
    proposal_id: int,
    body: FeedbackIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Pide modificación: status → draft (espera nueva versión) + registra
    el feedback. La próxima generación en la misma sesión crea version+1.
    """
    proposal = _get_owned_proposal(proposal_id, current_user["user_id"])

    _set_status(proposal_id, "draft")
    approval = _record_approval(
        proposal_id=proposal_id,
        decision="modified",
        feedback=body.feedback,
        previous_content=proposal.content,
    )
    return ApprovalOut(
        id=approval.id,
        proposal_id=approval.proposal_id,
        decision=approval.decision,
        feedback=approval.feedback,
        created_at=approval.created_at.isoformat() if approval.created_at else None,
    )
