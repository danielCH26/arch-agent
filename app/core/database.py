import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Usamos DATABASE_URL para que Chainlit detecte y active su data layer.
# (Necesario para que aparezca el sidebar de sesiones)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://asistente:asistente@localhost:5432/asistente_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
