-- Migration 0008: proposal generation, interaction auditing, and approvals

CREATE TABLE IF NOT EXISTS proposals (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    iteration INTEGER NOT NULL CHECK (iteration > 0),
    content JSONB NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    feedback TEXT,
    lifecycle VARCHAR(16) NOT NULL DEFAULT 'proposed'
        CHECK (lifecycle IN ('proposed', 'approved', 'rejected')),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS interaction_logs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    action_type VARCHAR(32) NOT NULL CHECK (action_type IN ('generate', 'modify', 'approve', 'reject')),
    comment TEXT,
    prompt TEXT,
    response TEXT,
    model VARCHAR(255),
    tokens_used INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    decision VARCHAR(16) NOT NULL CHECK (decision IN ('approved', 'modified', 'rejected')),
    previous_output JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_project_iter ON proposals (project_id, iteration);
CREATE INDEX IF NOT EXISTS idx_proposals_project_lifecycle ON proposals (project_id, lifecycle);
CREATE INDEX IF NOT EXISTS idx_interaction_logs_project_phase_created ON interaction_logs (project_id, phase, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_interaction_logs_proposal ON interaction_logs (project_id, phase) WHERE phase = 'propuesta';
CREATE INDEX IF NOT EXISTS idx_approvals_proposal ON approvals (proposal_id, created_at DESC);
