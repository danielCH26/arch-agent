#!/usr/bin/env python3
"""
Utilidades compartidas para los scripts de seed.

Issue: Caso de ejemplo (seed)
Responsable: Sofía (Backend / Agente)
Sprint: 1

Reutiliza la misma convención de logging y conexión que scripts/init_db.py
para que todos los scripts de seed se comporten de forma consistente.
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
    """Logger simple con colores (misma convención que init_db.py)."""
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
    """Conecta a PostgreSQL y maneja errores igual que init_db.py."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        log(f"Conectado a: {DATABASE_URL}", "OK")
        return conn
    except psycopg2.OperationalError as e:
        log(f"No se pudo conectar: {e}", "ERROR")
        sys.exit(1)
