-- =============================================================================
-- Migration 0018: approvals — backfill project_id, extend index, previous_output
-- =============================================================================
-- HU10 v2 (proposal #109, spec REQ-SA-27/REQ-SA-16, design §Data Model).
--
-- Closes the v1 cross-project contamination bug (PR #78 blocker #2):
-- migration 0016 already added `project_id` as nullable + an index on
-- `(project_id, phase)`. This migration:
--
--   1. Backfills NULL `project_id` rows from `sessions.project_id` (F08 only
--      added the column nullable so old rows stayed NULL). Rows whose
--      session has no project_id stay NULL — logged as WARNING for manual
--      triage. NOT a blocker; the application layer treats NULL project_id
--      as "unknown project, do not anchor approval to it" (REQ-SA-27).
--
--   2. Adds an extended index `(project_id, phase, created_at DESC)` for the
--      hot read path "latest decision for (project, phase)" used by
--      GET /api/projects/{id}/phases (REQ-SA-12, REQ-SA-26) and the
--      FOR UPDATE concurrency path (REQ-SA-31). Coexists with F08's
--      `idx_approvals_project_phase` so we don't pay a reindex window
--      mid-deploy.
--
--   3. Adds `approvals.previous_output JSONB NOT NULL DEFAULT '{}'::jsonb`
--      (REQ-SA-16) and `approvals.payload JSONB`. These let HU10 v2 snapshot
--      the prior LLM output on `modify` decisions and replay it on demand.
--      Nullable `payload_hash` carries the (action, payload_hash)
--      idempotency key (REQ-SA-30).
--
-- All statements are idempotent (ADD COLUMN IF NOT EXISTS, CREATE INDEX IF
-- NOT EXISTS, UPDATE ... WHERE ... IS NULL). Rollback = DROP COLUMN
-- previous_output/payload/payload_hash + DROP INDEX ix_approvals_project_phase_created.
-- No destructive schema drops, no data deletion.
-- =============================================================================

-- 1. Backfill project_id from sessions for legacy rows.
UPDATE approvals a
SET project_id = s.project_id
FROM sessions s
WHERE a.session_id = s.id
  AND a.project_id IS NULL
  AND s.project_id IS NOT NULL;

-- 2. Extended index for (project, phase, created_at DESC).
CREATE INDEX IF NOT EXISTS ix_approvals_project_phase_created
    ON approvals (project_id, phase, created_at DESC);

-- 3. previous_output + payload + payload_hash columns.
ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS previous_output JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS payload JSONB;

ALTER TABLE approvals
    ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(32);