from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Proposal(Base):
    """Persisted architecture proposal; see ADR-008 and ADR-009."""

    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint("lifecycle IN ('proposed', 'approved', 'rejected')", name="ck_proposals_lifecycle"),
        UniqueConstraint("project_id", "iteration", name="uq_proposals_project_iteration"),
        Index("idx_proposals_project_lifecycle", "project_id", "lifecycle"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    iteration = Column(Integer, nullable=False)
    content = Column(JSONB, nullable=False)
    citations = Column(JSONB, nullable=False, default=list, server_default="[]")
    feedback = Column(Text)
    lifecycle = Column(String(16), nullable=False, default="proposed", server_default="proposed")
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now())
