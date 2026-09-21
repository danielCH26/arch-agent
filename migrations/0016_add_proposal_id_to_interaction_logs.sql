-- =============================================================================
-- Migration 0016: PR #78 review F2 — scope proposal idempotency by proposal_id.
--
-- ``decide_proposal`` documented idempotency on (proposal_id, action_type) but
-- the actual query filtered on (project_id, phase, action_type). Once ANY
-- propuesta for a project was decided, every future iteration 409'd forever,
-- breaking the Modify -> new iteration -> Approve cycle.
--
-- This migration adds the nullable ``proposal_id`` FK the filter needs.
-- Legacy rows stay NULL: NULL never matches an equality predicate against a
-- real proposal_id in SQL, so old audit rows stop blocking new iterations
-- (existing behaviour for already decided legacy proposals is preserved —
-- their lifecycle is terminal anyway).
--
-- Reference: PR #78 review finding F2 (lau2413).
-- Idempotent: every statement uses IF NOT EXISTS so a re-run of
-- migrations/run_migrations.py is a no-op.
-- =============================================================================

ALTER TABLE interaction_logs
  ADD COLUMN IF NOT EXISTS proposal_id INTEGER REFERENCES proposals(id) ON DELETE SET NULL;

-- Read-path index for the (proposal_id, action_type) idempotency fingerprint.
CREATE INDEX IF NOT EXISTS idx_interaction_logs_proposal_action
  ON interaction_logs (proposal_id, action_type);

-- Down migration (run only manually if rollback is required):
-- DROP INDEX IF EXISTS idx_interaction_logs_proposal_action;
-- ALTER TABLE interaction_logs DROP COLUMN IF EXISTS proposal_id;
