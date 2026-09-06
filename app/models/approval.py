from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Approval(Base):
    """Decision and frozen prior output for a proposal."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'modified', 'rejected')", name="ck_approvals_decision"),
        Index("idx_approvals_proposal", "proposal_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String(16), nullable=False)
    previous_output = Column(JSONB)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

