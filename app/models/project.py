from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Boolean, ForeignKey, func
from app.core.database import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(50), default="active")
    current_phase = Column(String(50))
    # True cuando el LLM (o, mientras F08 no esté listo, un botón de prueba)
    # determina que ya se cumplió todo lo necesario de la fase actual y se
    # puede avanzar a la siguiente. Se resetea a False cada vez que se avanza.
    phase_ready = Column(Boolean, nullable=False, default=False, server_default="false")
    # True solo para el proyecto del seed (scripts/seed_example.py). Los
    # endpoints que listan proyectos de un usuario real deben excluirlo
    # (ver migration 0006 / comentario A3 en revisión del PR de seed).
    is_demo = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())