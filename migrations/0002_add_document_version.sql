-- =============================================================================
-- Migration 0002: versionado de documentos subidos al RAG
-- HU13: Subir archivos PDF/MD al RAG
-- Issue: #8
-- =============================================================================
-- Cambios:
-- 1. Columna `version` para soportar múltiples versiones del mismo archivo
-- 2. Columna `file_size_bytes` (puede faltar en schemas viejos)
-- 3. UNIQUE constraint (user_id, filename, version) — evita duplicados exactos
-- 4. Índice (user_id, created_at) — queries rápidas de "mis documentos"
-- =============================================================================

-- 1. Columna version
ALTER TABLE uploaded_documents
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- 2. file_size_bytes (puede faltar en schemas previos)
ALTER TABLE uploaded_documents
    ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER;

-- 3. UNIQUE constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uniq_uploaded_user_filename_version'
    ) THEN
        ALTER TABLE uploaded_documents
            ADD CONSTRAINT uniq_uploaded_user_filename_version
            UNIQUE (user_id, filename, version);
    END IF;
END $$;

-- 4. Índice (user_id, created_at DESC)
CREATE INDEX IF NOT EXISTS idx_uploaded_documents_user_created
    ON uploaded_documents (user_id, created_at DESC);
