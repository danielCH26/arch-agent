-- 0013 — GIN index on messages.attachments for JSONB containment lookup.
--
-- Used by app/api/attachments.py:_lookup_attachment (Postgres path) to
-- resolve one attachment by user_id + id without loading all of a user's
-- messages. Required by the F13 review fix for C3.
--
-- jsonb_path_ops is the minimal opclass for @> containment: smaller index,
-- faster lookups, no support for key-existence queries (which we don't need).
--
-- IF NOT EXISTS makes the migration idempotent. CONCURRENTLY is NOT used
-- because the migration runner (scripts/run_migrations.py) is transaction-
-- per-file; plain CREATE INDEX takes a brief ACCESS EXCLUSIVE lock on
-- messages, which is acceptable for the current table size (< 100k rows
-- per the demo seed). For production at higher scale, revisit via F14.
--
-- Idempotent: safe to re-run.

CREATE INDEX IF NOT EXISTS idx_messages_attachments_gin
ON messages
USING GIN (attachments jsonb_path_ops);
