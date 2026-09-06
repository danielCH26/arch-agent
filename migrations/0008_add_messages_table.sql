-- =============================================================================
-- Migration 0008: tabla messages (chat history)
-- =============================================================================
-- Capability: engram-conversation-memory (F12, issue #14).
-- Source of truth: Postgres. Engram receives a fire-and-forget sibling
-- observation via app/core/message_store.engram_mirror (REQ-6, ADR-011).
--
-- Idempotent (CREATE TABLE IF NOT EXISTS) so it is safe to re-run via
-- migrations/run_migrations.py (SCN-8). Mirrors the table block in
-- schema.sql for greenfield DBs (init_db.py without the migration runner).
--
-- Note on schema.sql sync: a CI guard (tests/test_schema_sync.py) is
-- documented as future work — F12 keeps the two definitions in lock-step
-- manually. See design.md §15 risk #10.
-- =============================================================================

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    engram_observation_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT messages_role_check CHECK (role IN ('user','assistant','system'))
);

-- Indices for the two access paths message_store / GET /api/chat/history use.
-- 1) (session_id, created_at DESC, id DESC) — list_recent on session.
CREATE INDEX IF NOT EXISTS idx_messages_session_id_created_at
    ON messages (session_id, created_at DESC, id DESC);

-- 2) (user_id, project_id, created_at DESC) — cross-user isolation on history.
CREATE INDEX IF NOT EXISTS idx_messages_user_id_project_id
    ON messages (user_id, project_id, created_at DESC);
