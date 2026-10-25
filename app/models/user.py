from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, Boolean, func
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    llm_base_url = Column(String(500))
    llm_model = Column(String(100))
    encrypted_api_key = Column(Text)
    # True solo para el usuario del seed (scripts/seed_example.py). No debe
    # poder autenticarse: su password_hash no es un hash bcrypt válido
    # (ver migration 0006 / comentario A1 en revisión del PR de seed).
    is_demo_user = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())