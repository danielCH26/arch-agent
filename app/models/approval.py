from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class Approval(Base):
    """
    Decisión del usuario sobre una fase del flujo (aprobar/modificar/
    rechazar). Feature 3: Refinamiento y validación por etapas (HU8).
    Issue #21 / HU10: ``previous_output`` carries a JSONB snapshot of the
    content being approved so a Modify decision can re-render the prior
    state without an extra round-trip to the originating phase endpoint.
    """

    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase = Column(String(50), nullable=False)
    decision = Column(String(20), nullable=False)  # 'approved' | 'modified' | 'rejected'
    feedback = Column(Text)
    # HU10 (REQ-SA-3 / REQ-SA-16): JSONB snapshot of the content that was on
    # screen when the user clicked Modificar; populated by the domain helper
    # app/core/phase_decisions.record_decision before INSERT. NOT NULL DEFAULT '{}'
    # is enforced at the DB level via migration 0015.
    previous_output = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(TIMESTAMP, server_default=func.now())
