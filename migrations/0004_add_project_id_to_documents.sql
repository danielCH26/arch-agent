-- =============================================================================
-- Migration 0004: vincular documentos a proyecto
-- HU13 (extensión): el botón de adjuntar del chat sube documentos al RAG,
-- y los documentos se asocian al proyecto activo.
-- =============================================================================
-- Issue: #8
-- Cambio: agregar columna project_id a uploaded_documents
-- (para poder filtrar documentos por proyecto activo)

ALTER TABLE uploaded_documents
    ADD COLUMN IF NOT EXISTS project_id INTEGER;

-- Índice para filtrar rápido por (user_id, project_id)
CREATE INDEX IF NOT EXISTS idx_uploaded_documents_user_project
    ON uploaded_documents (user_id, project_id);