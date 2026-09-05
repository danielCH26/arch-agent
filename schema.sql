-- =============================================================================
-- Schema inicial de arch-agent (aplicado por scripts/init_db.py).
--
-- Las migraciones incrementales viven en migrations/NNNN_*.sql (ver
-- migrations/run_migrations.py). Este archivo representa el estado "base"
-- de la DB; las migrations agregan columnas que los modelos SQLAlchemy
-- esperan pero que el schema inicial no contemplaba.
--
-- Para desarrollo nuevo: correr init_db.py + run_migrations.py.
-- Las columnas definidas acá con ADD COLUMN IF NOT EXISTS cubren lo mismo
-- que las migrations, para que init_db solo produzca una DB consistente.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

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

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',
    current_phase VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- HU2: recordar sesión del usuario
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    active_phase VARCHAR(50),
    engram_state JSONB,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Solo una sesión activa por usuario. Si re-ejecuta init_db.py despues de
-- migrations 0003, el UNIQUE INDEX ya existe y este CREATE es idempotente.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_user_id_unique ON sessions (user_id);

CREATE TABLE IF NOT EXISTS uploaded_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(20),
    file_size_bytes INTEGER,
    chunk_count INTEGER,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES uploaded_documents(id) ON DELETE CASCADE,
    chunk_text TEXT,
    chunk_index INTEGER,
    embedding vector(384),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id);

-- architect_patterns (issue "Caso de ejemplo (seed)" / comentario C2 de PR):
-- agregada acá también, no solo en migration 0005, para que una DB
-- greenfield (init_db.py sin correr migrations aún) ya la tenga.
CREATE TABLE IF NOT EXISTS architect_patterns (
    id SERIAL PRIMARY KEY,
    pattern_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    description TEXT,
    use_cases TEXT,
    tradeoffs JSONB,
    when_not_to_use TEXT,
    decision_signals JSONB,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_architect_patterns_embedding
    ON architect_patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_architect_patterns_category
    ON architect_patterns (category);

CREATE TABLE IF NOT EXISTS architect_pattern_chunks (
    id SERIAL PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES architect_patterns(id) ON DELETE CASCADE,
    chunk_type VARCHAR(50) NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pattern_chunks_embedding
    ON architect_pattern_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_pattern_chunks_pattern_id
    ON architect_pattern_chunks (pattern_id);

-- =============================================================================
-- Columnas agregadas en migrations pero incluidas aca para DBs nuevas.
-- init_db.py aplica todo en orden; migrations/run_migrations.py es idempotente.
-- =============================================================================

-- projects.phase_ready (migration 0001)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS phase_ready BOOLEAN NOT NULL DEFAULT FALSE;

-- uploaded_documents.version (migration 0002)
ALTER TABLE uploaded_documents ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- uploaded_documents.project_id (migration 0004)
ALTER TABLE uploaded_documents ADD COLUMN IF NOT EXISTS project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE;

-- users.is_demo_user / projects.is_demo (migration 0006, comentarios A1 y A3
-- de la revisión del PR de "Caso de ejemplo (seed)"): permiten que el login
-- (#57) y los endpoints de listado filtren explícitamente al usuario/proyecto
-- del seed. El demo_user NO debe poder autenticarse nunca.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_demo_user BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT FALSE;

