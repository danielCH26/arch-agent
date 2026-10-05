-- ===========================================================================
-- Schema de Base de Datos: arch-agent
-- ===========================================================================
-- Issue: #2 - [F02] Arquitectura técnica del sistema
-- Responsable: Daniel
-- Última actualización: 2026-08-23
--
-- Este schema define 8 tablas en PostgreSQL 16 + PGVector:
--   Relacionales: users, projects, sessions, interaction_logs, approvals,
--                 uploaded_documents
--   Vectoriales:  architect_patterns, document_chunks
-- ===========================================================================

-- Habilitar extensión vector (requerida para PGVector)
CREATE EXTENSION IF NOT EXISTS vector;

-- ===========================================================================
-- TABLAS RELACIONALES
-- ===========================================================================

-- ----------------------------------------------------------------------------
-- users: Usuarios del sistema
-- ----------------------------------------------------------------------------
CREATE TABLE users (
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

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);

-- ----------------------------------------------------------------------------
-- projects: Proyectos del usuario (cada proyecto es una iniciativa de
--           diseño de arquitectura)
-- ----------------------------------------------------------------------------
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',
    current_phase VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_projects_status ON projects(status);

-- ----------------------------------------------------------------------------
-- sessions: Sesiones de trabajo (cada ejecución del agente para un proyecto)
-- ----------------------------------------------------------------------------
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'in_progress',
    context_data JSONB,
    decisions JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessions_project_id ON sessions(project_id);
CREATE INDEX idx_sessions_phase ON sessions(phase);
CREATE INDEX idx_sessions_status ON sessions(status);

-- ----------------------------------------------------------------------------
-- interaction_logs: Log de cada llamada al LLM (auditoría completa)
--                   Es el fallback de Langfuse
-- ----------------------------------------------------------------------------
CREATE TABLE interaction_logs (
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

CREATE INDEX idx_interaction_logs_session_id ON interaction_logs(session_id);
CREATE INDEX idx_interaction_logs_phase ON interaction_logs(phase);
CREATE INDEX idx_interaction_logs_created_at ON interaction_logs(created_at);

-- ----------------------------------------------------------------------------
-- approvals: Aprobaciones del usuario (HU10, HU11)
--            Control de usuario sobre cada fase
-- ----------------------------------------------------------------------------
CREATE TABLE approvals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    decision VARCHAR(20) NOT NULL,  -- 'approved', 'modified', 'rejected'
    feedback TEXT,
    previous_output JSONB,
    regenerated_output JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_decision CHECK (decision IN ('approved', 'modified', 'rejected'))
);

CREATE INDEX idx_approvals_session_id ON approvals(session_id);
CREATE INDEX idx_approvals_decision ON approvals(decision);

-- ----------------------------------------------------------------------------
-- uploaded_documents: Metadata de documentos subidos al RAG (HU13)
-- ----------------------------------------------------------------------------
CREATE TABLE uploaded_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(20),
    chunk_count INTEGER,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_uploaded_documents_user_id ON uploaded_documents(user_id);
CREATE INDEX idx_uploaded_documents_processed ON uploaded_documents(processed);

-- ===========================================================================
-- TABLAS VECTORIALES (PGVector)
-- ===========================================================================

-- ----------------------------------------------------------------------------
-- architect_patterns: Patrones de arquitectura (seed inicial)
--                     Vector de 384 dimensiones (multilingual-e5-small)
-- ----------------------------------------------------------------------------
CREATE TABLE architect_patterns (
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

-- Índice IVFFLAT para búsqueda vectorial rápida (cosine similarity)
CREATE INDEX idx_architect_patterns_embedding
    ON architect_patterns USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_architect_patterns_category ON architect_patterns(category);

-- ----------------------------------------------------------------------------
-- architect_pattern_chunks: Chunks indexables de patrones de arquitectura
-- ----------------------------------------------------------------------------
CREATE TABLE architect_pattern_chunks (
    id SERIAL PRIMARY KEY,
    pattern_id INTEGER NOT NULL REFERENCES architect_patterns(id) ON DELETE CASCADE,
    chunk_type VARCHAR(50) NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(384),
    chunk_metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pattern_chunks_embedding
    ON architect_pattern_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_pattern_chunks_pattern_id ON architect_pattern_chunks(pattern_id);

-- ----------------------------------------------------------------------------
-- document_chunks: Chunks de documentos subidos por el usuario (HU13)
-- ----------------------------------------------------------------------------
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES uploaded_documents(id) ON DELETE CASCADE,
    chunk_text TEXT,
    chunk_index INTEGER,
    embedding vector(384),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índice IVFFLAT para búsqueda vectorial rápida
CREATE INDEX idx_document_chunks_embedding
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_document_chunks_document_id ON document_chunks(document_id);

-- ===========================================================================
-- TRIGGERS
-- ===========================================================================

-- Actualizar updated_at automáticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ===========================================================================
-- DATOS INICIALES (seed)
-- ===========================================================================

-- Aquí iría el seed de patrones de arquitectura (50 patrones iniciales)
-- Se carga vía scripts/seed_patterns.py (no en este schema)

-- ===========================================================================
-- FIN DEL SCHEMA
-- ===========================================================================
-- Total de tablas: 8 (6 relacionales + 2 vectoriales)
-- Total de índices: 14
-- Extensiones requeridas: vector (PGVector)
-- ===========================================================================
