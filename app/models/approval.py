from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class Approval(Base):
    """
    Decision del usuario sobre una fase del flujo (aprobar/modificar/
    rechazar). Feature 3: Refinamiento y validación por etapas (HU8).

    HU10 v2 (Engram sdd/hu10-staged-approvals-v2/spec, ADR-015) añade:
      * `previous_output` (REQ-SA-16): snapshot del output LLM previo al
        modify. ``{}`` por defecto; obligatorio en decisiones `modify`.
      * `payload` (REQ-SA-30): payload arbitrario del request (p.ej. la
        lista de trade-offs editados en `revision`).
      * `payload_hash` (REQ-SA-30): SHA256 hex truncado de
        ``canonical_json({action, payload})`` -- idempotency key per
        ``(project_id, phase, action, payload_hash)`` dentro de una ventana
        de 60s.

    El filtro de lectura es siempre por `(project_id, phase)` -- NO por
    `session_id`, porque `sessions.user_id` es UNIQUE (una fila por
    usuario, no por proyecto, hallazgo de la revisión
    `feature/hu6-diagrama`). Migration 0016 añadió `project_id`; migration
    0018 hizo el backfill desde `sessions.project_id`.
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
    # HU10 v2 (migration 0018, REQ-SA-16): snapshot del output previo. El
    # default '{}' cubre las decisiones que NO son modify (approve/reject)
    # y las filas anteriores a 0018; las decisiones modify deben poblarlo
    # explícitamente.
    previous_output = Column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="'{}'::jsonb",
    )
    # HU10 v2 (migration 0018, REQ-SA-30): payload arbitrario del request.
    # Nullable porque no todas las decisiones llevan payload (approve sin
    # feedback no tiene payload).
    payload = Column(JSONB, nullable=True)
    # HU10 v2 (migration 0018, REQ-SA-30): SHA256 hex[:32] de
    # canonical_json({action, payload}). Permite que un retry idéntico
    # dentro de 60s retorne 200 idempotent sin INSERT nuevo.
    payload_hash = Column(String(32), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())