-- Migration 0014: proposal generation, interaction auditing, and proposal_approvals (F08)
-- Renamed from 0008 to avoid number collision with F05's 0007/0008 approvals migrations.

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

CREATE TABLE IF NOT EXISTS proposal_approvals (
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
CREATE INDEX IF NOT EXISTS idx_proposal_approvals_proposal ON proposal_approvals (proposal_id, created_at DESC);