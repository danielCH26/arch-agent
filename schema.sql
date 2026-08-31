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
    ON document_chunks USING ivfflat (embedding vector_cosine_ops);

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

-- proposals (migration 0005)
CREATE TABLE IF NOT EXISTS proposals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL DEFAULT 'architecture',
    version INTEGER NOT NULL DEFAULT 1,
    content JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, version)
);

-- approvals (migration 0005)
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES proposals(id) ON DELETE CASCADE,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('approved', 'modified', 'rejected')),
    feedback TEXT,
    previous_content JSONB,
    modified_content JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- interaction_logs extensions (migration 0005)
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS phase VARCHAR(50);
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS proposal_id INTEGER REFERENCES proposals(id);
ALTER TABLE interaction_logs ADD COLUMN IF NOT EXISTS rag_patterns_used JSONB;

CREATE INDEX IF NOT EXISTS idx_proposals_session ON proposals (session_id, version);
CREATE INDEX IF NOT EXISTS idx_approvals_proposal ON approvals (proposal_id);