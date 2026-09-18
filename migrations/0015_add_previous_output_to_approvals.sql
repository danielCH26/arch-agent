-- =============================================================================
-- Migration 0015: HU10 staged-approvals — generalize approvals with previous_output JSONB,
-- widen the decision CHECK to accept body verbs (imperative) in addition to past-participle
-- values written by the legacy F05 path (app/api/elicitation.py via DECISION_TO_DB).
--
-- Reference: docs/adr/014-hu10-phase-gate.md §3 (decision key decision).
-- Idempotent: every statement uses IF NOT EXISTS / IF EXISTS so a re-run of
-- migrations/run_migrations.py is a no-op.
-- =============================================================================

ALTER TABLE approvals
  ADD COLUMN IF NOT EXISTS previous_output JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Widening of CHECK constraint chk_approvals_decision (created in migration 0008).
-- The constraint now accepts both forms so existing F05 participle rows stay valid
-- AND the new HU10 generic endpoint can insert imperative verbs. The domain helper
-- app/core/phase_decisions.py normalizes imperative -> participle before INSERT, so
-- new rows always use the past-participle form; the imperative form is admitted
-- defensively against old writers that pass the raw body verb.
ALTER TABLE approvals DROP CONSTRAINT IF EXISTS chk_approvals_decision;

ALTER TABLE approvals
  ADD CONSTRAINT chk_approvals_decision
  CHECK (decision IN ('approved', 'modified', 'rejected', 'approve', 'modify', 'reject'));

-- Read-path index for "last approved decision per (project, phase)".
-- The spec REQ-SA-18 referenced session_id; this table has no project_id column
-- so the index keys off session_id (the only project-scoped FK on this table).
CREATE INDEX IF NOT EXISTS idx_approvals_session_phase_created
  ON approvals (session_id, phase, created_at DESC);

-- Down migration (run only manually if rollback is required):
-- ALTER TABLE approvals DROP COLUMN IF EXISTS previous_output;
-- ALTER TABLE approvals DROP CONSTRAINT IF EXISTS chk_approvals_decision;
-- ALTER TABLE approvals
--   ADD CONSTRAINT chk_approvals_decision
--   CHECK (decision IN ('approved', 'modified', 'rejected'));
-- DROP INDEX IF EXISTS idx_approvals_session_phase_created;