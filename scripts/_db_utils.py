"""
Utilidades compartidas entre scripts/init_db.py y los scripts de seed
(seed_common.py, y por extensión seed_patterns.py, seed_example.py,
seed.py).

Antes vivían duplicadas en init_db.py y seed_common.py por separado —
este módulo es la única fuente de verdad para log()/connect_db()
(comentario A2 en la revisión del PR de "Caso de ejemplo (seed)").
"""

import os
import sys

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://asistente:asistente@postgres-app:5432/asistente_db",
)


def log(msg: str, level: str = "INFO"):
    """Logger simple con colores."""
    colors = {
        "INFO": "\033[94m",
        "OK": "\033[92m",
        "WARN": "\033[93m",
        "ERROR": "\033[91m",
    }
    reset = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{level}]{reset} {msg}")


def connect_db():
    """Conecta a PostgreSQL y maneja errores."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        log(f"Conectado a: {DATABASE_URL}", "OK")
        return conn
    except psycopg2.OperationalError as e:
        log(f"No se pudo conectar: {e}", "ERROR")
        sys.exit(1)