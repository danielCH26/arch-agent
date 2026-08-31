-- =============================================================================
-- Migration 0005: tablas proposals y approvals
-- F08 — Generación propuesta + aprobación
-- Issue: #12
-- =============================================================================
-- Crea:
-- 1. proposals: cada propuesta generada por el agente
-- 2. approvals: cada decisión del usuario (approved/modified/rejected)
-- 3. Extiende interaction_logs con phase, proposal_id, rag_patterns_used
-- =============================================================================

-- 1. Tabla proposals
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

-- 2. Tabla approvals
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES proposals(id) ON DELETE CASCADE,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('approved', 'modified', 'rejected')),
    feedback TEXT,
    previous_content JSONB,
    modified_content JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Extender interaction_logs
ALTER TABLE interaction_logs
    ADD COLUMN IF NOT EXISTS phase VARCHAR(50);

ALTER TABLE interaction_logs
    ADD COLUMN IF NOT EXISTS proposal_id INTEGER REFERENCES proposals(id);

ALTER TABLE interaction_logs
    ADD COLUMN IF NOT EXISTS rag_patterns_used JSONB;

-- 4. Índices
CREATE INDEX IF NOT EXISTS idx_proposals_session
    ON proposals (session_id, version);

CREATE INDEX IF NOT EXISTS idx_approvals_proposal
    ON approvals (proposal_id);
