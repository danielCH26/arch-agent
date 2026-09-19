-- =============================================================================
-- Migration 0012: índices de document_chunks para búsqueda semántica
-- =============================================================================
-- Esta parte vivía originalmente en una migración 0005 propia (rama
-- feature/Pipeline_RAG_PGVector) que también creaba `architect_patterns`.
-- Esa tabla ya la crea la migración 0005 de la rama F03-caso-ejemplo-seed,
-- así que aquí solo queda la parte que no se solapaba: los índices de
-- document_chunks.
--
-- Renumbered from ``0007_*`` to ``0012_*`` in PR #76 review fix #4 (B4):
-- ``0007_add_approvals.sql`` (F05) also lives under slot 0007 and both
-- files coexisting on disk made ``migrations/`` harder to scan and tripped
-- a reviewer asking which slot the chunks-index migration should occupy.
-- We picked 0012 because slot 0011 is already used by F13's
-- ``0011_add_message_attachments.sql`` (the previous PR #76 fix #3), so
-- 0012 keeps the post-F12 migrations adjacent without colliding with the
-- F07 lineage (slots 0008_add_pattern_context_and_chunks / 0009_add_
-- metadata_to_pattern_chunks) or the F08 proposal migration
-- (``0014_proposal_approvals_table.sql``).
--
-- The SQL DDL is identical and idempotent (``CREATE INDEX IF NOT
-- EXISTS``); the rename only affects the filename. ``run_migrations.py``
-- is keyed by filename, so a DB that previously applied
-- ``0007_add_document_chunks_indexes.sql`` will need the matching
-- ``schema_migrations`` row updated manually before re-running, OR the
-- DB will simply re-apply the renamed file (still a no-op thanks to
-- ``IF NOT EXISTS``).
-- =============================================================================

CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks (document_id);