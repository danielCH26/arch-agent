import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.env import env_int

# Usamos DATABASE_URL para que Chainlit detecte y active su data layer.
# (Necesario para que aparezca el sidebar de sesiones)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://asistente:asistente@localhost:5432/asistente_db",
)

# SQLAlchemy ya utiliza QueuePool para PostgreSQL. Estos valores hacen su
# capacidad y sus límites configurables por despliegue, con defaults seguros.
DB_POOL_SIZE = env_int("DB_POOL_SIZE", 10, minimum=1)
DB_MAX_OVERFLOW = env_int("DB_MAX_OVERFLOW", 20, minimum=0)
DB_POOL_TIMEOUT = env_int("DB_POOL_TIMEOUT", 30, minimum=1)
DB_POOL_RECYCLE = env_int("DB_POOL_RECYCLE", 1800, minimum=1)  # 0 = reciclar en cada checkout

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_recycle=DB_POOL_RECYCLE,
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
