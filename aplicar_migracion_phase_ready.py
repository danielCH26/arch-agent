"""
Aplica el ALTER TABLE usando la misma conexión que ya usa tu app
(SessionLocal / engine de SQLAlchemy), sin necesitar psql ni Alembic.

Correr una sola vez:
    python aplicar_migracion_phase_ready.py
"""
from sqlalchemy import text
from app.core.database import engine  # ajusta el import si tu engine se llama distinto

with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS phase_ready BOOLEAN NOT NULL DEFAULT FALSE;"
    ))
    conn.commit()

print("Columna 'phase_ready' agregada (o ya existía).")