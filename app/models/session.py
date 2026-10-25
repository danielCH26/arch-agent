from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, JSON, func
from app.core.database import Base

class UserSession(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"))
    active_phase = Column(String(50))
    engram_state = Column(JSON)
    last_seen_at = Column(TIMESTAMP, server_default=func.now())
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())