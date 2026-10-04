import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Usamos DATABASE_URL para que Chainlit detecte y active su data layer.
# (Necesario para que aparezca el sidebar de sesiones)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://asistente:asistente@localhost:5432/asistente_db",
)

# Las sesiones se siguen cerrando al terminar cada operación, pero sus
# conexiones TCP quedan disponibles en este pool para el siguiente request.
# Esto evita el handshake de PostgreSQL en cada búsqueda RAG. Los valores son
# deliberadamente conservadores y se pueden ajustar por despliegue.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

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
