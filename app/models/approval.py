from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, func
from app.core.database import Base


class Approval(Base):
    """
    Decisión del usuario sobre una fase del flujo (aprobar/modificar/
    rechazar). Feature 3: Refinamiento y validación por etapas (HU8).
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
    created_at = Column(TIMESTAMP, server_default=func.now())
