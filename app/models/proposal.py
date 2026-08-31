"""
Modelos SQLAlchemy para F08 — proposals y approvals.

Issue: #12 — F08 Generación propuesta + aprobación

- Proposal: cada propuesta generada por el agente (con versionado)
- Approval: cada decisión del usuario (approved/modified/rejected)
"""

import json
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column, Integer, String, ForeignKey, TIMESTAMP, CheckConstraint,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class Proposal(Base):
    """Propuesta de arquitectura generada por el agente."""

    __tablename__ = "proposals"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase = Column(String(50), nullable=False, default="architecture")
    version = Column(Integer, nullable=False, default=1)
    # content: {title, components, technologies, patterns, rationale, raw_text}
    content = Column(JSONB, nullable=False)
    # status: draft | pending_approval | approved | rejected | general
    status = Column(String(20), nullable=False, default="draft")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    # Constraints
    __table_args__ = (
        UniqueConstraint("session_id", "version", name="uq_proposals_session_version"),
    )

    # Relationship con approvals
    approvals = relationship(
        "Approval",
        backref="proposal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serializa a dict para enviar por SSE."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "phase": self.phase,
            "version": self.version,
            "content": self.content,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Approval(Base):
    """Decisión del usuario sobre una propuesta (approved/modified/rejected)."""

    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    proposal_id = Column(
        Integer,
        ForeignKey("proposals.id", ondelete="CASCADE"),
        nullable=False,
    )
    # decision: 'approved' | 'modified' | 'rejected'
    decision = Column(String(20), nullable=False)
    feedback = Column(String)
    previous_content = Column(JSONB)
    modified_content = Column(JSONB)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'modified', 'rejected')",
            name="ck_approvals_decision",
        ),
    )
