"""
Runner simple de migraciones SQL, sin Alembic.

Convención: migrations/000N_descripcion.sql, numeradas en orden.
Este script:
  1. Crea una tabla schema_migrations si no existe (para saber qué ya se aplicó).
  2. Recorre migrations/*.sql en orden numérico.
  3. Aplica solo las que no estén registradas todavía.

Correr:
    python migrations/run_migrations.py
"""
import os
import re
from pathlib import Path

from sqlalchemy import text
from app.core.database import engine

MIGRATIONS_DIR = Path(__file__).parent


def get_applied(conn) -> set[str]:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename VARCHAR(255) PRIMARY KEY,"
        "  applied_at TIMESTAMP DEFAULT NOW()"
        ")"
    ))
    rows = conn.execute(text("SELECT filename FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def main():
    sql_files = sorted(
        [f for f in MIGRATIONS_DIR.glob("*.sql") if re.match(r"^\d+_", f.name)],
        key=lambda f: f.name,
    )

    with engine.connect() as conn:
        applied = get_applied(conn)

        pending = [f for f in sql_files if f.name not in applied]
        if not pending:
            print("No hay migraciones pendientes.")
            return

        for f in pending:
            print(f"Aplicando {f.name}...")
            sql = f.read_text(encoding="utf-8")
            conn.execute(text(sql))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:filename)"),
                {"filename": f.name},
            )
            conn.commit()
            print(f"  OK: {f.name}")

        print(f"{len(pending)} migración(es) aplicada(s).")


if __name__ == "__main__":
    main()
