-- =============================================================================
-- Migration 0007: índices de document_chunks para búsqueda semántica
-- =============================================================================
-- Esta parte vivía originalmente en una migración 0005 propia (rama
-- feature/Pipeline_RAG_PGVector) que también creaba `architect_patterns`.
-- Esa tabla ya la crea la migración 0005 de la rama F03-caso-ejemplo-seed,
-- así que aquí solo queda la parte que no se solapaba: los índices de
-- document_chunks.
-- =============================================================================

CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks (document_id);