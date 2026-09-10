-- =============================================================================
-- Migration 0011: messages.attachments JSONB (F13, issue #17)
-- =============================================================================
-- Capability: chat-attachments (REQ-ATT-1) + engram-conversation-memory DELTA-1.
--
-- Additive, idempotent; re-runs against an F12-era DB add the column without
-- data loss (DEFAULT '[]'::jsonb on every existing row), and re-runs against
-- an F13-era DB are no-ops (ADD COLUMN IF NOT EXISTS).
--
-- The column is the storage for one or more ``Attachment`` typed dicts (UUID,
-- kind, mime, filename, storage_path, source_url, bytes). See
-- ``app/core/message_store.py`` for the helper API and
-- ``app/core/attachment_tokens.py`` for the signed-token auth.
--
-- Renumbered 0009 -> 0011 in PR #76 review fix #3, paired with
-- ``0010_add_messages_table.sql`` (was 0008). SQL DDL is unchanged.
-- =============================================================================

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS attachments JSONB NOT NULL DEFAULT '[]'::jsonb;