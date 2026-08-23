#!/usr/bin/env python3
"""
Script de inicialización de la base de datos.

Issue: #2 - [F02] Arquitectura técnica del sistema
Responsable: Daniel

Uso:
    docker compose exec app python scripts/init_db.py

Qué hace:
1. Habilita la extensión PGVector
2. Crea las 8 tablas (si no existen)
3. Carga el seed de patrones de arquitectura
4. Verifica la conexión
"""

import os
import sys
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://asistente:asistente@postgres-app:5432/asistente_db"
)

# Schema SQL embebido (mismo que docs/database/schema.sql)
SCHEMA_SQL = """
-- Habilitar extensión vector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabla users
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    llm_base_url VARCHAR(500),
    llm_model VARCHAR(100),
    encrypted_api_key TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla projects
CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',
    current_phase VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);

-- Tabla sessions
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'in_progress',
    context_data JSONB,
    decisions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_project_id ON sessions(project_id);

-- Tabla interaction_logs
CREATE TABLE IF NOT EXISTS interaction_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50),
    prompt TEXT,
    response TEXT,
    model VARCHAR(100),
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_interaction_logs_session_id ON interaction_logs(session_id);

-- Tabla approvals
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('approved', 'modified', 'rejected')),
    feedback TEXT,
    previous_output JSONB,
    regenerated_output JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla uploaded_documents
CREATE TABLE IF NOT EXISTS uploaded_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(20),
    chunk_count INTEGER,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_uploaded_documents_user_id ON uploaded_documents(user_id);

-- Tabla architect_patterns (vectorial)
CREATE TABLE IF NOT EXISTS architect_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    description TEXT,
    use_cases TEXT,
    tradeoffs JSONB,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla document_chunks (vectorial)
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES uploaded_documents(id) ON DELETE CASCADE,
    chunk_text TEXT,
    chunk_index INTEGER,
    embedding vector(384),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices IVFFLAT (solo si existen datos, sino avisar)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_architect_patterns_embedding') THEN
        CREATE INDEX idx_architect_patterns_embedding
            ON architect_patterns USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_document_chunks_embedding') THEN
        CREATE INDEX idx_document_chunks_embedding
            ON document_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
    END IF;
END $$;
"""


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
    print(f"{color}[{level}]\033[0m {msg}")


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


def check_pgvector_extension(conn):
    """Verifica que la extensión PGVector esté disponible."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector';")
    available = cur.fetchone()
    if not available:
        log(
            "La extensión 'vector' (PGVector) no está disponible en esta imagen.",
            "ERROR",
        )
        log(
            "Asegúrate de usar la imagen: pgvector/pgvector:pg16",
            "ERROR",
        )
        sys.exit(1)
    log("Extensión PGVector disponible", "OK")


def create_schema(conn):
    """Crea todas las tablas, índices y triggers."""
    log("Creando schema (8 tablas, índices, triggers)...")
    cur = conn.cursor()
    try:
        cur.execute(SCHEMA_SQL)
        log("Schema creado exitosamente", "OK")
    except psycopg2.Error as e:
        log(f"Error creando schema: {e}", "ERROR")
        sys.exit(1)


def verify_schema(conn):
    """Verifica que las 8 tablas existan."""
    expected_tables = {
        "users",
        "projects",
        "sessions",
        "interaction_logs",
        "approvals",
        "uploaded_documents",
        "architect_patterns",
        "document_chunks",
    }

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
        log(f"Faltan tablas: {missing}", "ERROR")
        sys.exit(1)

    log(f"Las 8 tablas están presentes: {sorted(existing_tables & expected_tables)}", "OK")


def verify_pgvector_works(conn):
    """Hace un test simple de PGVector."""
    cur = conn.cursor()
    try:
        # Crear vector dummy, calcular distancia
        cur.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector AS distance;")
        distance = cur.fetchone()[0]
        log(f"PGVector funcional (test distance = {distance:.4f})", "OK")
    except psycopg2.Error as e:
        log(f"PGVector no funciona: {e}", "ERROR")
        sys.exit(1)


def seed_initial_data_placeholder(conn):
    """Placeholder para el seed (se carga en Sprint 2)."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM architect_patterns;")
    count = cur.fetchone()[0]
    if count == 0:
        log(
            "Tabla architect_patterns vacía. El seed se cargará en Sprint 2 (F07).",
            "WARN",
        )
    else:
        log(f"architect_patterns ya tiene {count} patrones cargados", "OK")


def main():
    """Función principal."""
    log("=" * 60)
    log("Inicializando base de datos arch-agent")
    log("=" * 60)

    # 1. Conectar
    conn = connect_db()

    try:
        # 2. Verificar PGVector disponible
        check_pgvector_extension(conn)

        # 3. Crear schema
        create_schema(conn)

        # 4. Verificar schema
        verify_schema(conn)

        # 5. Test funcional de PGVector
        verify_pgvector_works(conn)

        # 6. Verificar seed (placeholder)
        seed_initial_data_placeholder(conn)

        log("=" * 60)
        log("Base de datos inicializada correctamente ✓", "OK")
        log("=" * 60)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
