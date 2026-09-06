"""Proposal API router (F08).

Mirrors ``app/api/chat.py``'s SSE shape verbatim per ADR-009:
``event: sources|token|done|error`` with the same headers. The only
divergence from chat is the ``done`` payload, which additionally carries
``proposal_id`` so the frontend can hydrate ``proposalsStore.currentProposal``
from a single round-trip.

Endpoints:
    POST /api/proposals/generate       -- SSE stream (new iteration = 1)
    POST /api/proposals/{id}/modify    -- SSE stream (iteration + 1)
    POST /api/proposals/{id}/decide    -- JSON (approve | modify | reject)
    GET  /api/proposals/{id}           -- JSON (read by id)

The route is mounted under ``/api/proposals`` from ``server.py``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.core.database import SessionLocal
from app.core.proposal_generator import ProposalGenerator, RAG_MIN_SIMILARITY
from app.models import Approval, InteractionLog, Proposal
from app.models.project import Project

logger = logging.getLogger(__name__)

# Re-declared to avoid the circular import (see app/core/proposal_generator.py
# docstring + design.md §9). MUST stay in sync with app/api/chat.py and
# app/core/proposal_generator.py until the rag_config refactor lands.
RAG_MIN_SIMILARITY = RAG_MIN_SIMILARITY

# Phase that proposals rejected from `propuesta` should bounce back to.
# Per REQ-8 / SCN-9: ops can override via env (e.g. to keep the user in the
# same phase instead of forcing them back to requerimientos).
PROPOSAL_REJECT_REVERTS_TO = os.getenv("PROPOSAL_REJECT_REVERTS_TO", "requerimientos")

# Per-project iteration cap (REQ-9 + design §17 #6).
PROPOSAL_MAX_ITER = int(os.getenv("PROPOSAL_MAX_ITER", "5"))


router = APIRouter(prefix="/api/proposals", tags=["proposals"])


# --- Request / response models --------------------------------------------


class GenerateRequest(BaseModel):
    project_id: int = Field(..., description="Project to draft a proposal for")


class ModifyRequest(BaseModel):
    feedback: str = Field(..., min_length=1, max_length=2000)


class DecideRequest(BaseModel):
    # ``modify`` is accepted at the wire level so the frontend can dispatch
    # the Modificar button (which actually triggers a separate ``/modify``
    # endpoint) without a separate Pydantic model; here it becomes a no-op
    # decision because the actual iteration is created upstream.
    decision: Literal["approve", "modify", "reject"]
    comment: Optional[str] = Field(None, max_length=2000)


class ProposalOut(BaseModel):
    id: int
    project_id: int
    iteration: int
    content: str
    citations: list[dict]
    feedback: Optional[str]
    lifecycle: str
    created_at: str


# --- SSE helper -----------------------------------------------------------


def _emit_sse(event: str, data) -> str:
    """Build a single SSE frame. Mirrors ``app/api/chat.py``'s inline format.

    Kept module-level (no closure over request state) so it can be unit-tested
    in isolation -- see ``tests/api/test_proposals.py``.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_stream(
    events: AsyncIterator[tuple[str, object]],
) -> AsyncIterator[str]:
    """Adapt the generator's ``(event, payload)`` tuples to SSE frames."""
    async for event, payload in events:
        yield _emit_sse(event, payload)


# --- Routes ---------------------------------------------------------------


@router.post("/generate")
async def generate_proposal(
    body: GenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream a new proposal as SSE.

    Sequence (see design SD-1):
        1. Validate ownership of ``project_id``.
        2. Call ``ProposalGenerator.generate_stream`` -- it yields
           ``sources``, then ``token``s, then ``done`` with ``proposal_id``.
        3. Any error short-circuits to ``event: error``.
    """
    user_id = int(current_user["user_id"])

    # Ownership pre-flight (the generator also enforces it; this gives us a
    # clean 404/403 instead of streaming an error event when the URL is wrong).
    db = SessionLocal()
    try:
        project = (
            db.query(Project)
            .filter(Project.id == body.project_id, Project.user_id == user_id)
            .first()
        )
        if project is None:
            exists = db.query(Project).filter(Project.id == body.project_id).first()
            if exists:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes acceso a este proyecto",
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Proyecto no encontrado",
            )
    finally:
        db.close()

    generator = ProposalGenerator(user_id=user_id, project_id=body.project_id)

    async def event_iterator():
        async for event, payload in generator.generate_stream(
            project_id=body.project_id
        ):
            yield event, payload

    return StreamingResponse(
        _sse_stream(event_iterator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{proposal_id}/modify")
async def modify_proposal(
    proposal_id: int,
    body: ModifyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Stream a new iteration as SSE, freezing the prior content in approvals.

    See design SD-2. The new proposal carries ``iteration = prior + 1`` and
    shares ``project_id`` with the prior row. The prior ``approvals`` row is
    inserted inside ``ProposalGenerator`` (before the new proposal) so an
    intermediate crash never leaves an orphan iteration without an audit
    trail.
    """
    user_id = int(current_user["user_id"])

    # Pre-flight: prior proposal must exist + belong to the caller.
    db = SessionLocal()
    try:
        prior = db.get(Proposal, proposal_id)
        if prior is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        owns_project = (
            db.query(Project)
            .filter(Project.id == prior.project_id, Project.user_id == user_id)
            .first()
        )
        if owns_project is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a esta propuesta",
            )
        if prior.lifecycle != "proposed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La propuesta ya está en estado '{prior.lifecycle}' "
                    "y no se puede modificar."
                ),
            )
        # Iteration cap pre-flight; the generator re-checks under write
        # lock but doing it here gives a clean 409 without streaming.
        if prior.iteration >= PROPOSAL_MAX_ITER:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Has alcanzado el máximo de iteraciones "
                    f"({PROPOSAL_MAX_ITER})"
                ),
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: int,
    body: DecideRequest,
    current_user: dict = Depends(get_current_user),
):
    """Approve / modify / reject a proposal.

    Approve: lifecycle -> approved, project.phase_ready = true.
    Reject: lifecycle -> rejected, project.current_phase reverts to
        ``PROPOSAL_REJECT_REVERTS_TO`` (default "requerimientos"), and
        ``phase_ready`` is reset to false so the user has to earn it again.
    Modify: no-op on lifecycle -- the actual iteration is created via the
        separate ``/modify`` endpoint. We still insert an interaction_log
        row tagged ``action_type='modify'`` for audit symmetry, but the
        row is created upstream so this branch returns 409 directing the
        client to POST ``/modify`` instead.

    Idempotency on ``(proposal_id, action_type)`` is enforced via the
    interaction_logs primary key + a check for an existing row with the
    same (proposal_id, action_type) inside the same transaction (design §10).
    """
    user_id = int(current_user["user_id"])

    if body.decision == "modify":
        # The modify flow is a separate streaming endpoint; this one is for
        # the final Aprobar/Rechazar clicks only.
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
        project = (
            db.query(Project)
            .filter(
                Project.id == proposal.project_id, Project.user_id == user_id
            )
            .first()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a esta propuesta",
            )
        if proposal.lifecycle != "proposed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La propuesta ya está en estado '{proposal.lifecycle}'."
                ),
            )

        # Idempotency check: same (proposal_id, action_type) row already?
        existing = (
            db.query(InteractionLog)
            .filter(
                InteractionLog.project_id == proposal.project_id,
                InteractionLog.phase == "propuesta",
                InteractionLog.action_type == (
                    "approve" if body.decision == "approve" else "reject"
                ),
            )
            .order_by(InteractionLog.created_at.desc())
            .first()
        )
        if existing is not None:
            # 409 with the actual lifecycle -- UI re-syncs via GET /{id}.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Esta propuesta ya fue "
                    f"{'aprobada' if body.decision == 'approve' else 'rechazada'}."
                ),
            )

        # Apply lifecycle transition + side effects.
        if body.decision == "approve":
            proposal.lifecycle = "approved"
            project.phase_ready = True
        else:  # reject
            proposal.lifecycle = "rejected"
            project.current_phase = PROPOSAL_REJECT_REVERTS_TO
            project.phase_ready = False

        # Audit row.
        db.add(
            InteractionLog(
                session_id=proposal.session_id,
                project_id=proposal.project_id,
                phase="propuesta",
                action_type="approve" if body.decision == "approve" else "reject",
                comment=body.comment,
            )
        )

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


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Read a proposal by id. JSON; ownership-checked."""
    user_id = int(current_user["user_id"])

    db = SessionLocal()
    try:
        proposal = db.get(Proposal, proposal_id)
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Propuesta no encontrada",
            )
        project = (
            db.query(Project)
            .filter(
                Project.id == proposal.project_id, Project.user_id == user_id
            )
            .first()
        )
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a esta propuesta",
            )

        content = proposal.content
        if isinstance(content, dict):
            content_str = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content_str = ""
        else:
            content_str = str(content)

        created_at = proposal.created_at.isoformat() if proposal.created_at else ""

        return ProposalOut(
            id=int(proposal.id),
            project_id=int(proposal.project_id),
            iteration=int(proposal.iteration),
            content=content_str,
            citations=list(proposal.citations or []),
            feedback=proposal.feedback,
            lifecycle=proposal.lifecycle,
            created_at=created_at,
        )
    finally:
        db.close()