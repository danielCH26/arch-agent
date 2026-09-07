from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class Message(Base):
    """Persisted chat turn (user / assistant / system).

    Postgres is the source of truth for retrieval (REQ-1, REQ-4); Engram
    receives a fire-and-forget sibling observation via the ``engram_mirror``
    helper (REQ-6, ADR-011). See ``docs/adr/011-engram-conversation-mirror.md``.
    """

    __tablename__ = "messages"

    # BIGSERIAL on Postgres (production) — falls back to plain INTEGER
    # on SQLite so the test suite can exercise the model without booting
    # a Postgres container. ``schema.sql`` still declares BIGSERIAL.
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    session_id = Column(
        Integer,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Postgres CHECK constraint enforced both in SQL and Python-side validation.
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    # JSONB on Postgres (default '[]'); plain JSON on SQLite for tests.
    # Stores the RAG sources emitted with the assistant response so the
    # frontend / history endpoint can replay them.
    citations = Column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        server_default=text("'[]'"),
    )
    # F13 (REQ-ATT-1 / REQ-EM-DELTA-1): one or more typed attachment dicts
    # (UUID, kind, mime, filename, storage_path, source_url, bytes). Mirrors
    # the ``citations`` pattern above; served via GET /api/chat/attachments/{id}.
    attachments = Column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        server_default=text("'[]'"),
    )
    # BIGINT NULL — populated only when the Engram mirror succeeds.
    engram_observation_id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system')",
            name="messages_role_check",
        ),
    )
