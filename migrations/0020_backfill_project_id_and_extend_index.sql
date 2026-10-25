-- =============================================================================
-- Migration 0020: approvals — backfill project_id, extend index, previous_output
-- =============================================================================
-- HU10 v2 (proposal #109, spec REQ-SA-27/REQ-SA-16, design §Data Model).
--
-- Closes the v1 cross-project contamination bug (PR #78 blocker #2):
-- migration 0016 already added `project_id` as nullable + an index on
-- `(project_id, phase)`. This migration:
--
--   1. Backfills NULL `project_id` rows from `sessions.project_id`, LIMITED
--      to users with exactly one project. (F08 only added the column
--      nullable so old rows stayed NULL; `sessions` has one row per user
--      and `sessions.project_id` is the last project that user opened, so
--      a blanket backfill would assign every legacy approval of a user to
--      their last project, mixing approvals across projects — review PR
--      #105, Soomri 2026-10-19.) For single-project users the session's
--      project_id is unambiguous, so the backfill is safe there. Rows that
--      stay NULL (session without project_id, or multi-project users) are
--      left for manual triage. NOT a blocker; the application layer treats
--      NULL project_id as "unknown project, do not anchor approval to it"
--      (REQ-SA-27).
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
--
-- Numeración: nació como 0018_backfill_project_id_and_extend_index.sql y se
-- renumeró a 0020 porque 0018 ya la usa F19 (0018_add_pattern_complexity.sql)
-- y 0019 la reserva el PR de fuentes de patrones (0019_add_pattern_sources.sql).
-- Como todo es idempotente, una base que ya aplicó el nombre viejo puede
-- volver a correrla con el nombre nuevo sin cambios.
-- =============================================================================

-- 1. Backfill project_id from sessions for legacy rows — only for users
--    with exactly one project (see header note 1).
UPDATE approvals a
SET project_id = s.project_id
FROM sessions s
WHERE a.session_id = s.id
  AND a.project_id IS NULL
  AND s.project_id IS NOT NULL
  AND (SELECT count(*) FROM projects p WHERE p.user_id = s.user_id) = 1;

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