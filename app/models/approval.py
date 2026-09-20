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
    # Migration 0016: sessions es 1 fila por usuario, no por proyecto, así
    # que session_id solo no alcanza para saber a qué proyecto pertenece
    # esta decisión (fuga de contexto entre proyectos del mismo usuario,
    # hallazgo #1 de la revisión feature/hu6-diagrama). Nullable porque las
    # filas creadas antes de esta migración no tienen este dato.
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Migration 0017: UUID del adjunto (messages.attachments[].id) sobre el que
    # se decidió, para las decisiones de la fase "diagram". Permite que el chat
    # y el historial recuerden qué diagramas ya tienen decisión (antes la
    # decisión era solo por proyecto y se perdía en un F5). NULL en el resto de
    # fases y en filas anteriores a la migración.
    attachment_id = Column(String(64), nullable=True)
    phase = Column(String(50), nullable=False)
    decision = Column(String(20), nullable=False)  # 'approved' | 'modified' | 'rejected'
    feedback = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
