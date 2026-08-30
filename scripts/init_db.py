"""
Script de inicializacion de la base de datos.

Uso:
    docker compose exec -T backend python scripts/init_db.py

Que hace:
1. Habilita/verifica la extension PGVector
2. Aplica el schema definido en schema.sql
3. Verifica las tablas declaradas en schema.sql
4. Verifica la conexion y PGVector
"""

import re
import sys
from pathlib import Path

import psycopg2

from _db_utils import connect_db, log

ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT_DIR / "schema.sql"


def load_schema_sql() -> str:
    """Lee schema.sql para mantener una sola fuente de verdad."""
    try:
        return SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as e:
        log(f"No se pudo leer {SCHEMA_PATH}: {e}", "ERROR")
        sys.exit(1)


def expected_tables_from_schema(schema_sql: str) -> set[str]:
    """Extrae las tablas declaradas en schema.sql para validar lo aplicado."""
    return set(
        re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w]*)",
            schema_sql,
            flags=re.IGNORECASE,
        )
    )


def check_pgvector_extension(conn):
    """Verifica que la extension PGVector este disponible."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector';")
    available = cur.fetchone()
    if not available:
        log(
            "La extension 'vector' (PGVector) no esta disponible en esta imagen.",
            "ERROR",
        )
        log("Asegurate de usar la imagen: pgvector/pgvector:pg16", "ERROR")
        sys.exit(1)
    log("Extension PGVector disponible", "OK")


def create_schema(conn, schema_sql: str):
    """Crea las tablas e indices definidos en schema.sql."""
    log(f"Aplicando schema desde {SCHEMA_PATH}...")
    cur = conn.cursor()
    try:
        cur.execute(schema_sql)
        log("Schema creado exitosamente", "OK")
    except psycopg2.Error as e:
        log(f"Error creando schema: {e}", "ERROR")
        sys.exit(1)


def verify_schema(conn, expected_tables: set[str]):
    """Verifica que existan las tablas declaradas en schema.sql."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    existing_tables = {row[0] for row in cur.fetchall()}

    missing = expected_tables - existing_tables
    if missing:
        log(f"Faltan tablas: {sorted(missing)}", "ERROR")
        sys.exit(1)

    log(f"Tablas presentes: {sorted(existing_tables & expected_tables)}", "OK")


def verify_pgvector_works(conn):
    """Hace un test simple de PGVector."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector AS distance;")
        distance = cur.fetchone()[0]
        log(f"PGVector funcional (test distance = {distance:.4f})", "OK")
    except psycopg2.Error as e:
        log(f"PGVector no funciona: {e}", "ERROR")
        sys.exit(1)


def main():
    """Funcion principal."""
    log("=" * 60)
    log("Inicializando base de datos arch-agent")
    log("=" * 60)

    schema_sql = load_schema_sql()
    expected_tables = expected_tables_from_schema(schema_sql)
    if not expected_tables:
        log(f"No se encontraron tablas declaradas en {SCHEMA_PATH}", "ERROR")
        sys.exit(1)

    conn = connect_db()

    try:
        check_pgvector_extension(conn)
        create_schema(conn, schema_sql)
        verify_schema(conn, expected_tables)
        verify_pgvector_works(conn)

        log("=" * 60)
        log("Base de datos inicializada correctamente", "OK")
        log("=" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    main()