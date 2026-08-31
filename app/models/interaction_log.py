from sqlalchemy import Column, Integer, String, TEXT, TIMESTAMP, ForeignKey, JSON, func
from app.core.database import Base


class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    phase = Column(String(50))
    prompt = Column(TEXT)
    response = Column(TEXT)
    model = Column(String(100))
    tokens_used = Column(Integer)
    latency_ms = Column(Integer)
    proposal_id = Column(Integer, ForeignKey("proposals.id", ondelete="SET NULL"))
    rag_patterns_used = Column(JSON)
    created_at = Column(TIMESTAMP, server_default=func.now())
