from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text, TIMESTAMP, func
from app.core.database import Base


class InteractionLog(Base):
    """Audit record for proposal interactions; see ADR-008 and ADR-009."""

    __tablename__ = "interaction_logs"
    __table_args__ = (
        CheckConstraint("action_type IN ('generate', 'modify', 'approve', 'reject')", name="ck_interaction_logs_action_type"),
        Index("idx_interaction_logs_project_phase_created", "project_id", "phase", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    phase = Column(String(50), nullable=False)
    action_type = Column(String(32), nullable=False)
    comment = Column(Text)
    prompt = Column(Text)
    response = Column(Text)
    model = Column(String(255))
    tokens_used = Column(Integer)
    latency_ms = Column(Integer)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
