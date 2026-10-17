-- =============================================================================
-- Migration 0019: architect_patterns.fuentes
-- =============================================================================
-- Conserva las referencias curadas del catálogo de patrones. Se mantienen en
-- JSONB para que cada patrón pueda enlazar varias fuentes con título y URL.
-- Después de aplicar esta migración ejecutar scripts/seed_patterns.py, igual
-- que se hizo con 0018, para poblar las filas existentes.
-- =============================================================================

ALTER TABLE architect_patterns
    ADD COLUMN IF NOT EXISTS fuentes JSONB NOT NULL DEFAULT '[]'::jsonb;
